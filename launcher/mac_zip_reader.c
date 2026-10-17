/*
 * macOS virtual-file bridge. Interpose file operations for indexed Android asset paths
 * and fetch their bytes from the loopback server.
 *
 * Editing notes: Use immediately unlinked temporary descriptors, not persistent
 * extracted media. The thread-local bypass prevents the hooks from recursively
 * intercepting their own work.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>

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

/* No persistent extracted media. Each ZIP read uses an immediately unlinked
   temporary file; it is released when its descriptor closes. */
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
    int fd = socket(AF_INET, SOCK_STREAM, 0);
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
        ssize_t w = send(fd, request + sent, n - sent, 0);
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
    const char *root = getenv("DANMACHI_ASSET_ROOT");
    if (root && !strncmp(path, root, strlen(root)) && path[strlen(root)] == '/') {
        const char *p = path + strlen(root) + 1;
        const char *rest = strchr(p, '/');
        if (rest && !strchr(rest + 1, '/') &&
            (strstr(rest + 1, "project.manifest") == rest + 1 ||
             strstr(rest + 1, "version.manifest") == rest + 1))
            return NULL;
        return p;
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
    char object[4096];
    const char *tmp = getenv("TMPDIR");
    if (!tmp) {
        close(net);
        errno = ENOENT;
        return -1;
    }
    snprintf(object, sizeof(object), "%s/zip-read-XXXXXX", tmp);
    int fd = mkstemp(object);
    if (fd >= 0) {
        unlink(object);
        fcntl(fd, F_SETFD, FD_CLOEXEC);
    }
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
    return fd;
}

// macOS interposition targets host libc, after Mac.apk translates guest paths.
static FILE *dm_fopen(const char *p, const char *m) {
    const char *n = logical(p);
    if (!n)
        return fopen(p, m);
    if (strcmp(m, "r") && strcmp(m, "rb")) {
        errno = EROFS;
        return NULL;
    }
    int fd = memory_file(n, O_RDONLY);
    if (fd < 0)
        return NULL;
    FILE *f = fdopen(fd, m);
    if (!f)
        close(fd);
    return f;
}
static int dm_stat(const char *p, struct stat *s) {
    int r = virtual_stat(p, s);
    return r == -2 ? stat(p, s) : r;
}
static int dm_lstat(const char *p, struct stat *s) {
    int r = virtual_stat(p, s);
    return r == -2 ? lstat(p, s) : r;
}
static int dm_access(const char *p, int m) {
    struct stat s;
    int r = virtual_stat(p, &s);
    if (r == -2)
        return access(p, m);
    if (r)
        return r;
    if (m & W_OK) {
        errno = EROFS;
        return -1;
    }
    return 0;
}
static int dm_open(const char *p, int f, ...) {
    const char *n = logical(p);
    if (n)
        return memory_file(n, f);
    mode_t m = 0;
    if (f & O_CREAT) {
        va_list a;
        va_start(a, f);
        m = va_arg(a, int);
        va_end(a);
    }
    return open(p, f, m);
}
static int dm_openat(int dir, const char *p, int f, ...) {
    const char *n = logical(p);
    if (n)
        return memory_file(n, f);
    mode_t m = 0;
    if (f & O_CREAT) {
        va_list a;
        va_start(a, f);
        m = va_arg(a, int);
        va_end(a);
    }
    return openat(dir, p, f, m);
}
#define HOOK(replacement, target)                                                      \
    __attribute__((used)) static struct {                                              \
        const void *r;                                                                 \
        const void *t;                                                                 \
    } hook_##target __attribute__((section("__DATA,__interpose"))) = {                 \
        (const void *)&replacement, (const void *)&target};
HOOK(dm_fopen, fopen)
HOOK(dm_stat, stat)
HOOK(dm_lstat, lstat)
HOOK(dm_access, access)
HOOK(dm_open, open)
HOOK(dm_openat, openat)
// CRI movie shader is adapted to sampler2D; match its Android OES binding.
static void (*movie_bind_real)(unsigned, unsigned);
static void (*movie_param_real)(unsigned, unsigned, int);
static void movie_bind(unsigned target, unsigned name) {
    if (target == 0x8D65) {
        target = 0x0DE1;
        static int logged;
        if (!logged++) {
            fprintf(stderr, "[movie] external texture binding mapped to 2D\n");
        }
    }
    movie_bind_real(target, name);
}
static void movie_param(unsigned target, unsigned key, int value) {
    movie_param_real(target == 0x8D65 ? 0x0DE1 : target, key, value);
}
// Also cover libraries that bind libc dynamically rather than through Mach-O stubs.
static void *dm_dlsym(void *h, const char *n) {
    void *p = dlsym(h, n);
    if (p && (!strcmp(n, "glBindFramebuffer") || !strcmp(n, "glBindFramebufferOES"))) {
        void *bridge = dlsym(RTLD_DEFAULT, "danmachi_scene_framebuffer");
        if (bridge)
            return bridge;
    }
    if (p && (!strcmp(n, "glViewport") || !strcmp(n, "glScissor"))) {
        const char *name = !strcmp(n, "glViewport") ? "danmachi_scene_viewport"
                                                    : "danmachi_scene_scissor";
        void *bridge = dlsym(RTLD_DEFAULT, name);
        if (bridge) {
            static int logged;
            if (!logged++) {
                fprintf(stderr, "[dm-dynamic-scene] GLES drawing bindings installed\n");
            }
            return bridge;
        }
    }
    if (p && !strcmp(n, "glBindTexture") && p != (void *)movie_bind) {
        movie_bind_real = p;
        return (void *)movie_bind;
    }
    if (p && !strcmp(n, "glTexParameteri") && p != (void *)movie_param) {
        movie_param_real = p;
        return (void *)movie_param;
    }
    if (p && (!strcmp(n, "fopen") || !strcmp(n, "fopen$DARWIN_EXTSN")))
        return (void *)&dm_fopen;
    if (p && (!strcmp(n, "stat") || !strcmp(n, "stat$INODE64")))
        return (void *)&dm_stat;
    if (p && (!strcmp(n, "lstat") || !strcmp(n, "lstat$INODE64")))
        return (void *)&dm_lstat;
    if (p && !strcmp(n, "access"))
        return (void *)&dm_access;
    if (p && (!strcmp(n, "open") || !strcmp(n, "open$NOCANCEL")))
        return (void *)&dm_open;
    if (p && (!strcmp(n, "openat") || !strcmp(n, "openat$NOCANCEL")))
        return (void *)&dm_openat;
    return p;
}
HOOK(dm_dlsym, dlsym)
// JVM dual-stack sockets express loopback as ::ffff:127.0.0.1. Convert
// only this project's port to IPv4, retaining the outbound sandbox guard.
static int dm_connect(int fd, const struct sockaddr *a, socklen_t len) {
    if (a->sa_family == AF_INET6) {
        const struct sockaddr_in6 *b = (const void *)a;
        if (IN6_IS_ADDR_V4MAPPED(&b->sin6_addr) && ntohs(b->sin6_port) == 28766 &&
            !memcmp(b->sin6_addr.s6_addr + 12, "\x7f\0\0\1", 4)) {
            struct sockaddr_in local = {.sin_len = sizeof(local),
                                        .sin_family = AF_INET,
                                        .sin_port = b->sin6_port,
                                        .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
            int replacement = socket(AF_INET, SOCK_STREAM, 0);
            if (replacement < 0)
                return -1;
            int flags = fcntl(fd, F_GETFL), desc = fcntl(fd, F_GETFD);
            if (flags >= 0)
                fcntl(replacement, F_SETFL, flags);
            if (desc >= 0)
                fcntl(replacement, F_SETFD, desc);
            int options[] = {SO_KEEPALIVE, SO_REUSEADDR, SO_RCVBUF, SO_SNDBUF};
            for (unsigned i = 0; i < sizeof(options) / sizeof(options[0]); i++) {
                int value;
                socklen_t size = sizeof(value);
                if (!getsockopt(fd, SOL_SOCKET, options[i], &value, &size))
                    setsockopt(replacement, SOL_SOCKET, options[i], &value, size);
            }
            int result = connect(replacement, (const void *)&local, sizeof(local));
            int saved = errno;
            if (dup2(replacement, fd) < 0) {
                close(replacement);
                return -1;
            }
            close(replacement);
            if (desc >= 0)
                fcntl(fd, F_SETFD, desc);
            errno = saved;
            return result;
        }
    }
    return connect(fd, a, len);
}
HOOK(dm_connect, connect)
