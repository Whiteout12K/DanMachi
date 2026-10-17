/*
 * Linux/Android virtual-file bridge retained as source. Match indexed asset paths and
 * fetch archive-backed bytes from the loopback server.
 *
 * Editing notes: Payloads use disposable RAM file descriptors. This is not the active
 * macOS build; launcher/mac_zip_reader.c is its host-specific counterpart.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/mman.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <dlfcn.h>
#include <time.h>

/* No filesystem cache. Every archived payload lives in a disposable RAM fd. */
typedef struct {
    char *path;
    uint64_t size;
} Entry;
static Entry *entries;
static uint32_t count;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static __thread int bypass;
// Read a complete protocol field; short reads are not a successful index response.
static int exact(int fd, void *buffer, size_t n) {
    char *p = buffer;
    while (n) {
        ssize_t got = read(fd, p, n);
        if (got <= 0)
            return -1;
        p += got;
        n -= got;
    }
    return 0;
}
// Open a bounded-time loopback request. The caller owns the returned descriptor.
static int http(const char *path, uint64_t *length) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
        return -1;
    struct timeval timeout = {20, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_in a = {.sin_family = AF_INET,
                            .sin_port = htons(28766),
                            .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    if (connect(fd, (void *)&a, sizeof(a)) < 0) {
        close(fd);
        return -1;
    }
    char request[15000];
    int n = snprintf(request, sizeof(request),
                     "GET %s HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n",
                     path);
    if (n <= 0 || n >= (int)sizeof(request)) {
        close(fd);
        errno = ENAMETOOLONG;
        return -1;
    }
    for (int sent = 0; sent < n;) {
        ssize_t w = send(fd, request + sent, n - sent, MSG_NOSIGNAL);
        if (w <= 0) {
            close(fd);
            return -1;
        }
        sent += w;
    }
    char header[8192];
    size_t used = 0;
    while (used < sizeof(header) - 1) {
        if (exact(fd, header + used, 1) < 0) {
            close(fd);
            return -1;
        }
        used++;
        if (used >= 4 && !memcmp(header + used - 4, "\r\n\r\n", 4))
            break;
    }
    header[used] = 0;
    if (!strstr(header, " 200 ")) {
        close(fd);
        errno = ENOENT;
        return -1;
    }
    char *size = strcasestr(header, "\r\nContent-Length:");
    if (!size) {
        close(fd);
        errno = EIO;
        return -1;
    }
    *length = strtoull(size + 17, 0, 10);
    return fd;
}
static const char *logical(const char *path) {
    if (!path || bypass)
        return NULL;
    const char *roots[] = {"/data/data/com.eu.danmore/files/contents/",
                           "/data/user/0/com.eu.danmore/files/contents/", NULL};
    for (int i = 0; roots[i]; i++) {
        size_t n = strlen(roots[i]);
        if (!strncmp(path, roots[i], n)) {
            const char *p = path + n;
            const char *rest = strchr(p, '/');
            if (rest && !strchr(rest + 1, '/') &&
                (strstr(rest + 1, "project.manifest") == rest + 1 ||
                 strstr(rest + 1, "version.manifest") == rest + 1))
                return NULL;
            return p;
        }
    }
    if (!strncmp(path, "files/contents/", 15))
        return path + 15;
    return NULL;
}
static int load_index(void) {
    pthread_mutex_lock(&lock);
    if (entries) {
        pthread_mutex_unlock(&lock);
        return 0;
    }
    uint64_t size;
    int fd = http("/zip-reader/index", &size);
    if (fd < 0 || size < 4 || size > 64 * 1024 * 1024) {
        if (fd >= 0)
            close(fd);
        pthread_mutex_unlock(&lock);
        return -1;
    }
    unsigned char *data = malloc(size + 1);
    if (!data || exact(fd, data, size)) {
        free(data);
        close(fd);
        pthread_mutex_unlock(&lock);
        return -1;
    }
    close(fd);
    data[size] = 0;
    uint32_t total;
    memcpy(&total, data, 4);
    if (total > 750000) {
        free(data);
        pthread_mutex_unlock(&lock);
        return -1;
    }
    Entry *table = calloc(total, sizeof(Entry));
    size_t offset = 4;
    uint32_t i;
    for (i = 0; table && i < total; i++) {
        uint16_t n;
        if (offset + 10 > size)
            break;
        memcpy(&n, data + offset, 2);
        memcpy(&table[i].size, data + offset + 2, 8);
        offset += 10;
        if (offset + n > size || !n)
            break;
        table[i].path = malloc(n + 1);
        if (!table[i].path)
            break;
        memcpy(table[i].path, data + offset, n);
        table[i].path[n] = 0;
        offset += n;
    }
    free(data);
    if (!table || i != total || offset != size) {
        if (table) {
            for (uint32_t k = 0; k < total; k++)
                free(table[k].path);
            free(table);
        }
        pthread_mutex_unlock(&lock);
        errno = EIO;
        return -1;
    }
    entries = table;
    count = total;
    pthread_mutex_unlock(&lock);
    return 0;
}
static int find(const char *name, uint64_t *size) {
    if (load_index())
        return -1;
    size_t lo = 0, hi = count;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        int c = strcmp(entries[mid].path, name);
        if (c < 0)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo < count && !strcmp(entries[lo].path, name)) {
        *size = entries[lo].size;
        return 1;
    }
    size_t n = strlen(name);
    while (n && name[n - 1] == '/')
        n--;
    if (lo < count && !strncmp(entries[lo].path, name, n) &&
        entries[lo].path[n] == '/') {
        *size = 0;
        return 2;
    }
    return 0;
}
static int virtual_stat(const char *path, struct stat *s) {
    const char *name = logical(path);
    if (!name)
        return -2;
    uint64_t size;
    int kind = find(name, &size);
    if (kind <= 0) {
        errno = kind < 0 ? EIO : ENOENT;
        return -1;
    }
    memset(s, 0, sizeof(*s));
    s->st_mode = (kind == 2 ? S_IFDIR | 0555 : S_IFREG | 0444);
    s->st_size = size;
    s->st_nlink = 1;
    s->st_blksize = 4096;
    s->st_uid = getuid();
    s->st_gid = getgid();
    return 0;
}
static int memory_file(const char *name, int flags) {
    if ((flags & O_ACCMODE) != O_RDONLY || (flags & (O_CREAT | O_TRUNC | O_APPEND))) {
        errno = EROFS;
        return -1;
    }
    uint64_t expected;
    int kind = find(name, &expected);
    if (kind != 1) {
        errno = kind == 2 ? EISDIR : ENOENT;
        return -1;
    }
    if (expected > 512 * 1024 * 1024) {
        errno = EFBIG;
        return -1;
    }
    char url[14000];
    strcpy(url, "/zip-reader/file?path=");
    size_t used = strlen(url);
    static const char hex[] = "0123456789ABCDEF";
    for (const unsigned char *p = (void *)name; *p; p++) {
        if (used + 4 >= sizeof(url)) {
            errno = ENAMETOOLONG;
            return -1;
        }
        if ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
            (*p >= '0' && *p <= '9') || strchr("/_.-", *p))
            url[used++] = *p;
        else {
            url[used++] = '%';
            url[used++] = hex[*p >> 4];
            url[used++] = hex[*p & 15];
        }
    }
    url[used] = 0;
    uint64_t size;
    int net = http(url, &size);
    if (net < 0)
        return -1;
    if (size != expected) {
        close(net);
        errno = EIO;
        return -1;
    }
    int fd = syscall(__NR_memfd_create, "DanMachi ZIP asset",
                     MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (fd < 0) {
        close(net);
        return -1;
    }
    char buffer[65536];
    while (size) {
        size_t n = size < sizeof(buffer) ? size : sizeof(buffer);
        if (exact(net, buffer, n)) {
            close(net);
            close(fd);
            errno = EIO;
            return -1;
        }
        size_t off = 0;
        while (off < n) {
            ssize_t w = write(fd, buffer + off, n - off);
            if (w <= 0) {
                close(net);
                close(fd);
                return -1;
            }
            off += w;
        }
        size -= n;
    }
    close(net);
    lseek(fd, 0, SEEK_SET);
    fcntl(fd, F_ADD_SEALS, F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL);
    return fd;
}
#define REAL(name, type)                                                               \
    static type original;                                                              \
    if (!original) {                                                                   \
        bypass++;                                                                      \
        original = (type)dlsym(RTLD_NEXT, #name);                                      \
        bypass--;                                                                      \
    }
int stat(const char *p, struct stat *s) {
    int r = virtual_stat(p, s);
    if (r != -2)
        return r;
    return syscall(__NR_newfstatat, AT_FDCWD, p, s, 0);
}
int lstat(const char *p, struct stat *s) {
    int r = virtual_stat(p, s);
    if (r != -2)
        return r;
    return syscall(__NR_newfstatat, AT_FDCWD, p, s, AT_SYMLINK_NOFOLLOW);
}
int fstatat(int d, const char *p, struct stat *s, int flags) {
    int r = virtual_stat(p, s);
    if (r != -2)
        return r;
    return syscall(__NR_newfstatat, d, p, s, flags);
}
int access(const char *p, int mode) {
    struct stat s;
    int r = virtual_stat(p, &s);
    if (r == -2)
        return syscall(__NR_faccessat, AT_FDCWD, p, mode, 0);
    if (r)
        return r;
    if (mode & W_OK) {
        errno = EROFS;
        return -1;
    }
    return 0;
}
int open(const char *p, int flags, ...) {
    const char *name = logical(p);
    if (name)
        return memory_file(name, flags);
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, int);
        va_end(args);
    }
    return syscall(__NR_openat, AT_FDCWD, p, flags, mode);
}
int openat(int d, const char *p, int flags, ...) {
    const char *name = logical(p);
    if (name)
        return memory_file(name, flags);
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, int);
        va_end(args);
    }
    return syscall(__NR_openat, d, p, flags, mode);
}
int __open_2(const char *p, int flags) {
    return open(p, flags);
}
int __openat_2(int d, const char *p, int flags) {
    return openat(d, p, flags);
}
FILE *fopen(const char *p, const char *mode) {
    const char *name = logical(p);
    if (name) {
        if (strcmp(mode, "r") && strcmp(mode, "rb")) {
            errno = EROFS;
            return NULL;
        }
        int fd = memory_file(name, O_RDONLY);
        if (fd < 0)
            return NULL;
        FILE *f = fdopen(fd, mode);
        if (!f)
            close(fd);
        return f;
    }
    typedef FILE *(*fn)(const char *, const char *);
    REAL(fopen, fn);
    return original ? original(p, mode) : NULL;
}
int stat64(const char *p, struct stat64 *s) {
    return stat(p, (struct stat *)s);
}
int lstat64(const char *p, struct stat64 *s) {
    return lstat(p, (struct stat *)s);
}
int fstatat64(int d, const char *p, struct stat64 *s, int f) {
    return fstatat(d, p, (struct stat *)s, f);
}
int open64(const char *p, int f, ...) {
    mode_t m = 0;
    if (f & O_CREAT) {
        va_list a;
        va_start(a, f);
        m = va_arg(a, int);
        va_end(a);
    }
    return open(p, f, m);
}
int openat64(int d, const char *p, int f, ...) {
    mode_t m = 0;
    if (f & O_CREAT) {
        va_list a;
        va_start(a, f);
        m = va_arg(a, int);
        va_end(a);
    }
    return openat(d, p, f, m);
}
FILE *fopen64(const char *p, const char *m) {
    return fopen(p, m);
}
