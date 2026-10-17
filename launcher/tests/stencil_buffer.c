/*
 * Native framebuffer diagnostic for retained stencil-mask behavior.
 *
 * Editing notes: This probe checks rendering capability; it does not replace in-game
 * visual verification.
 * Source navigation: docs/05-source-guide.md. Compiled outputs are separate.
 */

/* Regression probe: stencil masking must restrict the green draw to half the default framebuffer.
   Link bundled EGL/GLES and inject launcher/stencil_support.dylib. No game assets or saves are used. */
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>
extern void *eglGetDisplay(void *);
extern unsigned eglInitialize(void *, int *, int *);
extern unsigned eglChooseConfig(void *, const int *, void **, int, int *);
extern void *eglCreateContext(void *, void *, void *, const int *);
extern void *eglCreatePbufferSurface(void *, void *, const int *);
extern unsigned eglMakeCurrent(void *, void *, void *, void *);
extern unsigned eglGetError(void);
extern void glTexImage2D(unsigned, int, int, int, int, int, unsigned, unsigned,
                         const void *);
extern void glDrawArrays(unsigned, int, int);
extern void glGenTextures(int, unsigned *);
extern void glBindTexture(unsigned, unsigned);
extern void glTexParameteri(unsigned, unsigned, int);
extern void glGenFramebuffers(int, unsigned *);
extern void glBindFramebuffer(unsigned, unsigned);
extern void glFramebufferTexture2D(unsigned, unsigned, unsigned, unsigned, int);
extern unsigned glCheckFramebufferStatus(unsigned);
extern void glReadPixels(int, int, int, int, unsigned, unsigned, void *);
extern unsigned glGetError(void);
extern unsigned glCreateShader(unsigned);
extern void glShaderSource(unsigned, int, const char **, const int *);
extern void glCompileShader(unsigned);
extern unsigned glCreateProgram(void);
extern void glAttachShader(unsigned, unsigned);
extern void glBindAttribLocation(unsigned, unsigned, const char *);
extern void glLinkProgram(unsigned);
extern void glUseProgram(unsigned);
extern void glVertexAttribPointer(unsigned, int, unsigned, unsigned char, int,
                                  const void *);
extern void glEnableVertexAttribArray(unsigned);
extern void glViewport(int, int, int, int);
extern void glClearColor(float, float, float, float);
extern void glClear(unsigned);
extern void glClearStencil(int);
extern void glScissor(int, int, int, int);
extern void glEnable(unsigned);
extern void glDisable(unsigned);
extern void glStencilFunc(unsigned, int, unsigned);
extern void glStencilMask(unsigned);
int main() {
    void *d = eglGetDisplay(0);
    int a, b, n;
    if (!eglInitialize(d, &a, &b)) {
        printf("initialize error %x\n", eglGetError());
        return 1;
    }
    int ca[] = {0x3033, 1,      0x3040, 4,      0x3024, 8,     0x3023,
                8,      0x3022, 8,      0x3021, 8,      0x3038};
    void *c;
    if (!eglChooseConfig(d, ca, &c, 1, &n) || !n)
        return 2;
    int ctxa[] = {0x3098, 2, 0x3038}, sa[] = {0x3057, 4, 0x3056, 4, 0x3038};
    void *ctx = eglCreateContext(d, c, 0, ctxa);
    void *s = eglCreatePbufferSurface(d, c, sa);
    if (!eglMakeCurrent(d, s, s, ctx))
        return 3;
    void (*image)(unsigned, int, int, int, int, int, unsigned, unsigned, const void *) =
        glTexImage2D;
    unsigned tex, fb;
    unsigned char data[16] = {255, 0, 0, 255, 255, 0, 0, 255,
                              255, 0, 0, 255, 255, 0, 0, 255},
                  out[4] = {0};
    glGenTextures(1, &tex);
    glBindTexture(0xde1, tex);
    glTexParameteri(0xde1, 0x2801, 0x2600);
    image(0xde1, 0, 0x1908, 2, 2, 0, 0x1908, 0x1401, data);
    glGenFramebuffers(1, &fb);
    glBindFramebuffer(0x8d40, fb);
    glFramebufferTexture2D(0x8d40, 0x8ce0, 0xde1, tex, 0);
    unsigned status = glCheckFramebufferStatus(0x8d40);
    glReadPixels(0, 0, 1, 1, 0x1908, 0x1401, out);

    unsigned vs = glCreateShader(0x8b31), fs = glCreateShader(0x8b30);
    const char *v =
        "attribute vec2 position;void main(){gl_Position=vec4(position,0.,1.);}";
    const char *f =
        "precision mediump float;void main(){gl_FragColor=vec4(0.,1.,0.,1.);}";
    glShaderSource(vs, 1, &v, 0);
    glShaderSource(fs, 1, &f, 0);
    glCompileShader(vs);
    glCompileShader(fs);
    unsigned prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glBindAttribLocation(prog, 0, "position");
    glLinkProgram(prog);
    glUseProgram(prog);
    float verts[] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glVertexAttribPointer(0, 2, 0x1406, 0, 0, verts);
    glEnableVertexAttribArray(0);
    glViewport(0, 0, 2, 2);
    void (*drawarrays)(unsigned, int, int) = glDrawArrays;
    drawarrays(5, 0, 4);
    glReadPixels(0, 0, 1, 1, 0x1908, 0x1401, out);

    glBindFramebuffer(0x8d40, 0);
    glViewport(0, 0, 4, 4);
    glClearColor(1, 0, 0, 1);
    glClearStencil(0);
    glStencilMask(255);
    glClear(0x4000 | 0x400);
    glEnable(0xc11);
    glScissor(0, 0, 2, 4);
    glClearStencil(1);
    glClear(0x400);
    glDisable(0xc11);
    glEnable(0xb90);
    glStencilFunc(0x202, 1, 255);
    glStencilMask(0);
    drawarrays(5, 0, 4);
    unsigned char right[4];
    glReadPixels(0, 0, 1, 1, 0x1908, 0x1401, out);
    glReadPixels(3, 0, 1, 1, 0x1908, 0x1401, right);
    printf("mask left=%u,%u,%u right=%u,%u,%u\n", out[0], out[1], out[2], right[0],
           right[1], right[2]);
    if (right[0] != 255 || right[1] != 0)
        return 7;
    printf("fb=%x pixel=%u,%u,%u,%u error=%x\n", status, out[0], out[1], out[2], out[3],
           glGetError());
    return out[0] == 0 && out[1] == 255 && out[2] == 0 && out[3] == 255 ? 0 : 5;
}
