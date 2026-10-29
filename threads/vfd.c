// Pipes and eventfds that threads can share, for a threaded Pyodide.
//
// Emscripten keeps file descriptors in JavaScript on the main thread: other
// threads reach them through calls proxied to it, poll() ignores its timeout,
// and there's no eventfd. Code that wakes one thread from another through a
// file descriptor (libzmq, asyncio's event loops) needs all three. Here pipes
// and eventfds live in WebAssembly memory, guarded by one mutex, and poll()
// waits on a condition variable that every change signals.
//
// Linked into the main module, these definitions replace libc's, so CPython
// and side modules (which import them from the main module) get them too.
// Each pipe end or eventfd holds an open /dev/null descriptor, which reserves
// its number; anything else goes to Emscripten as before.

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>
#include <wasi/api.h>

int __syscall_poll(intptr_t fds, int nfds, int timeout);
int __syscall_fcntl64(int fd, int cmd, ...);
int __syscall_dup(int fd);
int __syscall_dup3(int fd, int suggestfd, int flags);

#define MAX_FDS 4096
#define PIPE_SIZE 65536
// how often poll() looks at Emscripten's descriptors while waiting on ours
#define REAL_FD_INTERVAL_NS 10000000

enum kind { EVENT, PIPE_READ, PIPE_WRITE };

struct pipe_buffer {
  char data[PIPE_SIZE];
  size_t start, length;
  int readers, writers;
};

struct vfd {
  enum kind kind;
  int nonblocking;
  int semaphore;
  uint64_t count;
  struct pipe_buffer* pipe;
  // descriptors sharing it (dup)
  int refs;
};

static struct vfd* vfds[MAX_FDS];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;

static int
fail(int error)
{
  errno = error;
  return -1;
}

static int
wasi_result(__wasi_errno_t error)
{
  return error ? fail(error) : 0;
}

static struct vfd*
lookup(int fd)
{
  if (fd < 0 || fd >= MAX_FDS) {
    return NULL;
  }
  return __atomic_load_n(&vfds[fd], __ATOMIC_ACQUIRE);
}

// with the lock held
static void
attach(int fd, struct vfd* v)
{
  v->refs++;
  __atomic_store_n(&vfds[fd], v, __ATOMIC_RELEASE);
}

// with the lock held
static void
detach(int fd)
{
  struct vfd* v = lookup(fd);
  if (!v) {
    return;
  }
  __atomic_store_n(&vfds[fd], NULL, __ATOMIC_RELEASE);
  if (--v->refs == 0) {
    struct pipe_buffer* p = v->pipe;
    if (p) {
      if (v->kind == PIPE_READ) {
        p->readers--;
      } else {
        p->writers--;
      }
      if (p->readers == 0 && p->writers == 0) {
        free(p);
      }
    }
    free(v);
  }
  pthread_cond_broadcast(&changed);
}

// gives a duplicated descriptor the same pipe end or eventfd
static int
share(int fd, struct vfd* v)
{
  if (fd < 0 || !v) {
    return fd;
  }
  if (fd >= MAX_FDS) {
    (void)__wasi_fd_close(fd);
    return fail(EMFILE);
  }
  pthread_mutex_lock(&lock);
  attach(fd, v);
  pthread_mutex_unlock(&lock);
  return fd;
}

// a descriptor number for a new pipe end or eventfd
static int
reserve(struct vfd* v)
{
  int fd = open("/dev/null", O_RDWR);
  if (fd < 0) {
    return -1;
  }
  return share(fd, v);
}

static short
ready_events(struct vfd* v)
{
  struct pipe_buffer* p = v->pipe;
  switch (v->kind) {
    case EVENT:
      return (v->count > 0 ? POLLIN : 0) |
             (v->count < UINT64_MAX - 1 ? POLLOUT : 0);
    case PIPE_READ:
      return (p->length > 0 ? POLLIN : 0) | (p->writers == 0 ? POLLHUP : 0);
    case PIPE_WRITE:
      return (p->length < PIPE_SIZE ? POLLOUT : 0) |
             (p->readers == 0 ? POLLERR : 0);
  }
  return 0;
}

static void
deadline_after(struct timespec* deadline, long long ns)
{
  clock_gettime(CLOCK_REALTIME, deadline);
  ns += deadline->tv_nsec;
  deadline->tv_sec += ns / 1000000000;
  deadline->tv_nsec = ns % 1000000000;
}

static int
before(const struct timespec* a, const struct timespec* b)
{
  return a->tv_sec < b->tv_sec ||
         (a->tv_sec == b->tv_sec && a->tv_nsec < b->tv_nsec);
}

int
eventfd(unsigned int count, int flags)
{
  if (flags & ~(EFD_SEMAPHORE | EFD_NONBLOCK | EFD_CLOEXEC)) {
    return fail(EINVAL);
  }
  struct vfd* v = calloc(1, sizeof(*v));
  if (!v) {
    return fail(ENOMEM);
  }
  v->kind = EVENT;
  v->count = count;
  v->semaphore = !!(flags & EFD_SEMAPHORE);
  v->nonblocking = !!(flags & EFD_NONBLOCK);
  int fd = reserve(v);
  if (fd < 0) {
    free(v);
  }
  return fd;
}

int
eventfd_read(int fd, eventfd_t* value)
{
  return read(fd, value, sizeof(*value)) == sizeof(*value) ? 0 : -1;
}

int
eventfd_write(int fd, eventfd_t value)
{
  return write(fd, &value, sizeof(value)) == sizeof(value) ? 0 : -1;
}

int
pipe2(int fds[2], int flags)
{
  if (flags & ~(O_NONBLOCK | O_CLOEXEC)) {
    return fail(EINVAL);
  }
  struct pipe_buffer* p = calloc(1, sizeof(*p));
  struct vfd* ends[2] = { calloc(1, sizeof(struct vfd)),
                          calloc(1, sizeof(struct vfd)) };
  if (!p || !ends[0] || !ends[1]) {
    free(p);
    free(ends[0]);
    free(ends[1]);
    return fail(ENOMEM);
  }
  p->readers = p->writers = 1;
  for (int i = 0; i < 2; i++) {
    ends[i]->kind = i == 0 ? PIPE_READ : PIPE_WRITE;
    ends[i]->pipe = p;
    ends[i]->nonblocking = !!(flags & O_NONBLOCK);
  }
  fds[0] = reserve(ends[0]);
  if (fds[0] < 0) {
    free(p);
    free(ends[0]);
    free(ends[1]);
    return -1;
  }
  fds[1] = reserve(ends[1]);
  if (fds[1] < 0) {
    int error = errno;
    p->writers = 0;
    close(fds[0]);
    free(ends[1]);
    return fail(error);
  }
  return 0;
}

int
pipe(int fds[2])
{
  return pipe2(fds, 0);
}

static ssize_t
read_virtual(struct vfd* v, void* buffer, size_t size)
{
  ssize_t result;
  pthread_mutex_lock(&lock);
  if (v->kind == PIPE_WRITE) {
    result = fail(EBADF);
  } else if (v->kind == EVENT && size < sizeof(uint64_t)) {
    result = fail(EINVAL);
  } else if (v->kind == PIPE_READ && size == 0) {
    result = 0;
  } else {
    while (!(ready_events(v) & (POLLIN | POLLHUP))) {
      if (v->nonblocking) {
        pthread_mutex_unlock(&lock);
        return fail(EAGAIN);
      }
      pthread_cond_wait(&changed, &lock);
    }
    if (v->kind == EVENT) {
      uint64_t value = v->semaphore ? 1 : v->count;
      v->count -= value;
      memcpy(buffer, &value, sizeof(value));
      result = sizeof(value);
    } else {
      struct pipe_buffer* p = v->pipe;
      size_t n = size < p->length ? size : p->length;
      for (size_t i = 0; i < n; i++) {
        ((char*)buffer)[i] = p->data[(p->start + i) % PIPE_SIZE];
      }
      p->start = (p->start + n) % PIPE_SIZE;
      p->length -= n;
      result = n;
    }
    pthread_cond_broadcast(&changed);
  }
  pthread_mutex_unlock(&lock);
  return result;
}

static ssize_t
write_virtual(struct vfd* v, const void* buffer, size_t size)
{
  ssize_t result = 0;
  pthread_mutex_lock(&lock);
  if (v->kind == PIPE_READ) {
    result = fail(EBADF);
  } else if (v->kind == EVENT) {
    uint64_t value;
    if (size < sizeof(value)) {
      result = fail(EINVAL);
      goto done;
    }
    memcpy(&value, buffer, sizeof(value));
    if (value == UINT64_MAX) {
      result = fail(EINVAL);
      goto done;
    }
    while (v->count > UINT64_MAX - 1 - value) {
      if (v->nonblocking) {
        result = fail(EAGAIN);
        goto done;
      }
      pthread_cond_wait(&changed, &lock);
    }
    v->count += value;
    result = sizeof(value);
  } else {
    struct pipe_buffer* p = v->pipe;
    size_t written = 0;
    while (written < size) {
      if (p->readers == 0) {
        result = written ? (ssize_t)written : fail(EPIPE);
        goto done;
      }
      if (p->length == PIPE_SIZE) {
        if (v->nonblocking) {
          result = written ? (ssize_t)written : fail(EAGAIN);
          goto done;
        }
        pthread_cond_broadcast(&changed);
        pthread_cond_wait(&changed, &lock);
        continue;
      }
      while (written < size && p->length < PIPE_SIZE) {
        p->data[(p->start + p->length) % PIPE_SIZE] =
          ((const char*)buffer)[written++];
        p->length++;
      }
    }
    result = written;
  }
done:
  if (result > 0) {
    pthread_cond_broadcast(&changed);
  }
  pthread_mutex_unlock(&lock);
  return result;
}

ssize_t
read(int fd, void* buffer, size_t size)
{
  struct vfd* v = lookup(fd);
  if (v) {
    return read_virtual(v, buffer, size);
  }
  __wasi_iovec_t iov = { .buf = buffer, .buf_len = size };
  size_t n;
  if (wasi_result(__wasi_fd_read(fd, &iov, 1, &n))) {
    return -1;
  }
  return n;
}

ssize_t
write(int fd, const void* buffer, size_t size)
{
  struct vfd* v = lookup(fd);
  if (v) {
    return write_virtual(v, buffer, size);
  }
  __wasi_ciovec_t iov = { .buf = buffer, .buf_len = size };
  size_t n;
  if (wasi_result(__wasi_fd_write(fd, &iov, 1, &n))) {
    return -1;
  }
  return n;
}

int
close(int fd)
{
  if (lookup(fd)) {
    pthread_mutex_lock(&lock);
    detach(fd);
    pthread_mutex_unlock(&lock);
  }
  __wasi_errno_t error = __wasi_fd_close(fd);
  return wasi_result(error == __WASI_ERRNO_INTR ? 0 : error);
}

int
dup(int fd)
{
  int result = __syscall_dup(fd);
  return result < 0 ? fail(-result) : share(result, lookup(fd));
}

static int
dup_onto(int old, int new, int flags)
{
  int result;
  while ((result = __syscall_dup3(old, new, flags)) == -EBUSY) {
  }
  if (result < 0) {
    return fail(-result);
  }
  pthread_mutex_lock(&lock);
  detach(new);
  struct vfd* v = lookup(old);
  if (v) {
    attach(new, v);
  }
  pthread_mutex_unlock(&lock);
  return new;
}

int
dup2(int old, int new)
{
  if (old == new) {
    return __syscall_fcntl64(old, F_GETFD) < 0 ? fail(EBADF) : old;
  }
  if (new >= MAX_FDS && lookup(old)) {
    return fail(EMFILE);
  }
  return dup_onto(old, new, 0);
}

int
__dup3(int old, int new, int flags)
{
  if (old == new) {
    return fail(EINVAL);
  }
  if (new >= MAX_FDS && lookup(old)) {
    return fail(EMFILE);
  }
  return dup_onto(old, new, flags);
}

int
dup3(int old, int new, int flags)
{
  return __dup3(old, new, flags);
}

int
fcntl(int fd, int cmd, ...)
{
  unsigned long arg = 0;
  if (cmd != F_GETFL && cmd != F_GETFD && cmd != F_GETOWN) {
    va_list ap;
    va_start(ap, cmd);
    arg = va_arg(ap, unsigned long);
    va_end(ap);
  }
  struct vfd* v = lookup(fd);
  if (v && (cmd == F_GETFL || cmd == F_SETFL)) {
    pthread_mutex_lock(&lock);
    int result = 0;
    if (cmd == F_GETFL) {
      result = (v->kind == PIPE_READ    ? O_RDONLY
                : v->kind == PIPE_WRITE ? O_WRONLY
                                        : O_RDWR) |
               (v->nonblocking ? O_NONBLOCK : 0);
    } else {
      v->nonblocking = !!(arg & O_NONBLOCK);
      pthread_cond_broadcast(&changed);
    }
    pthread_mutex_unlock(&lock);
    return result;
  }
  // the rest is musl's fcntl: Emscripten has no F_DUPFD_CLOEXEC, so it falls
  // back to F_DUPFD
  int result;
  if (cmd == F_SETFL) {
    arg |= O_LARGEFILE;
  }
  if (cmd == F_GETOWN) {
    struct f_owner_ex ex;
    result = __syscall_fcntl64(fd, F_GETOWN_EX, &ex);
    if (result == -EINVAL) {
      result = __syscall_fcntl64(fd, cmd, (void*)arg);
    }
    if (result) {
      return result < 0 ? fail(-result) : result;
    }
    return ex.type == F_OWNER_PGRP ? -ex.pid : ex.pid;
  }
  if (cmd == F_DUPFD_CLOEXEC) {
    result = __syscall_fcntl64(fd, F_DUPFD_CLOEXEC, arg);
    if (result != -EINVAL) {
      return result < 0 ? fail(-result) : share(result, v);
    }
    result = __syscall_fcntl64(fd, F_DUPFD_CLOEXEC, 0);
    if (result != -EINVAL) {
      if (result >= 0) {
        (void)__wasi_fd_close(result);
      }
      return fail(EINVAL);
    }
    result = __syscall_fcntl64(fd, F_DUPFD, arg);
    return result < 0 ? fail(-result) : share(result, v);
  }
  switch (cmd) {
    case F_SETLK:
    case F_GETLK:
    case F_GETOWN_EX:
    case F_SETOWN_EX:
      result = __syscall_fcntl64(fd, cmd, (void*)arg);
      break;
    default:
      result = __syscall_fcntl64(fd, cmd, arg);
  }
  if (result >= 0 && cmd == F_DUPFD) {
    return share(result, v);
  }
  return result < 0 ? fail(-result) : result;
}

static int
poll_real(struct pollfd* fds, nfds_t n, int timeout)
{
  int result = __syscall_poll((intptr_t)fds, n, timeout);
  return result < 0 ? fail(-result) : result;
}

int
poll(struct pollfd* fds, nfds_t n, int timeout)
{
  nfds_t real_count = 0;
  int any_virtual = 0;
  for (nfds_t i = 0; i < n; i++) {
    if (lookup(fds[i].fd)) {
      any_virtual = 1;
    } else if (fds[i].fd >= 0) {
      real_count++;
    }
  }
  if (!any_virtual) {
    return poll_real(fds, n, timeout);
  }
  struct pollfd* real = NULL;
  if (real_count) {
    real = malloc(real_count * sizeof(*real));
    if (!real) {
      return fail(ENOMEM);
    }
  }
  struct timespec deadline;
  if (timeout > 0) {
    deadline_after(&deadline, timeout * 1000000LL);
  }
  int result;
  pthread_mutex_lock(&lock);
  for (;;) {
    nfds_t r = 0;
    for (nfds_t i = 0; i < n; i++) {
      struct vfd* v = lookup(fds[i].fd);
      fds[i].revents =
        v ? ready_events(v) & (fds[i].events | POLLERR | POLLHUP) : 0;
      if (!v && fds[i].fd >= 0 && r < real_count) {
        real[r++] = fds[i];
      }
    }
    if (real_count) {
      pthread_mutex_unlock(&lock);
      result = poll_real(real, real_count, 0);
      pthread_mutex_lock(&lock);
      if (result < 0) {
        break;
      }
      r = 0;
      for (nfds_t i = 0; i < n; i++) {
        if (!lookup(fds[i].fd) && fds[i].fd >= 0 && r < real_count) {
          fds[i].revents = real[r++].revents;
        }
      }
    }
    result = 0;
    for (nfds_t i = 0; i < n; i++) {
      result += fds[i].revents != 0;
    }
    if (result || timeout == 0) {
      break;
    }
    struct timespec now, wake;
    clock_gettime(CLOCK_REALTIME, &now);
    if (timeout > 0 && !before(&now, &deadline)) {
      break;
    }
    if (real_count) {
      deadline_after(&wake, REAL_FD_INTERVAL_NS);
      if (timeout > 0 && before(&deadline, &wake)) {
        wake = deadline;
      }
      pthread_cond_timedwait(&changed, &lock, &wake);
    } else if (timeout > 0) {
      pthread_cond_timedwait(&changed, &lock, &deadline);
    } else {
      pthread_cond_wait(&changed, &lock);
    }
  }
  pthread_mutex_unlock(&lock);
  free(real);
  return result;
}

int
select(int n,
       fd_set* restrict read_fds,
       fd_set* restrict write_fds,
       fd_set* restrict except_fds,
       struct timeval* restrict tv)
{
  if (n < 0 || n > FD_SETSIZE ||
      (tv && (tv->tv_sec < 0 || tv->tv_usec < 0))) {
    return fail(EINVAL);
  }
  struct pollfd fds[FD_SETSIZE];
  nfds_t count = 0;
  for (int fd = 0; fd < n; fd++) {
    short events = (read_fds && FD_ISSET(fd, read_fds) ? POLLIN : 0) |
                   (write_fds && FD_ISSET(fd, write_fds) ? POLLOUT : 0) |
                   (except_fds && FD_ISSET(fd, except_fds) ? POLLPRI : 0);
    if (events) {
      fds[count++] = (struct pollfd){ .fd = fd, .events = events };
    }
  }
  int timeout = -1;
  if (tv) {
    long long ms = tv->tv_sec * 1000LL + (tv->tv_usec + 999) / 1000;
    timeout = ms > INT32_MAX ? INT32_MAX : (int)ms;
  }
  int result = poll(fds, count, timeout);
  if (result < 0) {
    return result;
  }
  for (int fd = 0; fd < n; fd++) {
    if (read_fds) FD_CLR(fd, read_fds);
    if (write_fds) FD_CLR(fd, write_fds);
    if (except_fds) FD_CLR(fd, except_fds);
  }
  result = 0;
  for (nfds_t i = 0; i < count; i++) {
    short got = fds[i].revents;
    if (got & POLLNVAL) {
      return fail(EBADF);
    }
    if ((fds[i].events & POLLIN) && (got & (POLLIN | POLLHUP | POLLERR))) {
      FD_SET(fds[i].fd, read_fds);
      result++;
    }
    if ((fds[i].events & POLLOUT) && (got & (POLLOUT | POLLERR))) {
      FD_SET(fds[i].fd, write_fds);
      result++;
    }
    if ((fds[i].events & POLLPRI) && (got & POLLPRI)) {
      FD_SET(fds[i].fd, except_fds);
      result++;
    }
  }
  return result;
}
