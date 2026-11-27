/*
 * uvc2fb - 把 UVC 摄像头画面实时显示到 /dev/fb0
 *
 * 用法: ./uvc2fb [/dev/videoN]
 * 默认 /dev/video3，若不存在会自动扫描 /dev/video0~9 找 UVC 设备
 *
 * 采集: V4L2 + YUYV(mmap)，输出: 800x480 framebuffer(16/32bpp 自适应)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <linux/videodev2.h>
#include <linux/fb.h>

#define FB_PATH   "/dev/fb0"
#define REQ_BUFS  4

static volatile int g_run = 1;
static void on_sig(int s) { (void)s; g_run = 0; }

struct vbuf {
    void  *start;
    size_t length;
};

/* framebuffer 像素打包参数 */
static int fb_bpp, fb_line, fb_w, fb_h;
static int r_off, r_len, g_off, g_len, b_off, b_len;
static unsigned char *fb_mem;

static inline unsigned int pack(int r, int g, int b)
{
    unsigned int p;
    p  = (unsigned int)((r >> (8 - r_len)) << r_off);
    p |= (unsigned int)((g >> (8 - g_len)) << g_off);
    p |= (unsigned int)((b >> (8 - b_len)) << b_off);
    return p;
}

static inline int clip(int v)
{
    return v < 0 ? 0 : (v > 255 ? 255 : v);
}

/* ---------------- 5x7 点阵字体（只覆盖水印用到的字符） ---------------- */
struct glyph {
    char c;
    unsigned char rows[7];
};

static const struct glyph g_font[] = {
    {'0', {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}},
    {'1', {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}},
    {'2', {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}},
    {'3', {0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E}},
    {'4', {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}},
    {'5', {0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E}},
    {'6', {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}},
    {'7', {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}},
    {'8', {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}},
    {'9', {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}},
    {'.', {0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C}},
    {'C', {0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E}},
    {'T', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}},
    {'=', {0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00}},
    {'-', {0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00}},
    {' ', {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
};

static const struct glyph *find_glyph(char c)
{
    unsigned int i;
    for (i = 0; i < sizeof(g_font) / sizeof(g_font[0]); i++)
        if (g_font[i].c == c) return &g_font[i];
    return NULL;
}

static void fill_rect(int x, int y, int w, int h, unsigned int color)
{
    int dy, dx;
    for (dy = 0; dy < h; dy++) {
        unsigned char *row;
        if (y + dy < 0 || y + dy >= fb_h) continue;
        row = fb_mem + (size_t)(y + dy) * fb_line;
        for (dx = 0; dx < w; dx++) {
            if (x + dx < 0 || x + dx >= fb_w) continue;
            if (fb_bpp == 32) ((unsigned int *)row)[x + dx] = color;
            else ((unsigned short *)row)[x + dx] = (unsigned short)color;
        }
    }
}

static int draw_char(int x, int y, char c, int scale, unsigned int fg)
{
    const struct glyph *g = find_glyph(c);
    int r, col, dx, dy;

    if (!g) return 5 * scale;

    for (r = 0; r < 7; r++) {
        for (col = 0; col < 5; col++) {
            if (!(g->rows[r] & (1 << (4 - col)))) continue;
            for (dy = 0; dy < scale; dy++) {
                unsigned char *row;
                int py = y + r * scale + dy;
                if (py < 0 || py >= fb_h) continue;
                row = fb_mem + (size_t)py * fb_line;
                for (dx = 0; dx < scale; dx++) {
                    int px = x + col * scale + dx;
                    if (px < 0 || px >= fb_w) continue;
                    if (fb_bpp == 32) ((unsigned int *)row)[px] = fg;
                    else ((unsigned short *)row)[px] = (unsigned short)fg;
                }
            }
        }
    }
    return 5 * scale;
}

static void draw_text(int x, int y, const char *s, int scale, unsigned int fg)
{
    while (*s) {
        x += draw_char(x, y, *s, scale, fg) + scale;
        s++;
    }
}

/* ---------------- 温度（DS18B20）后台读取 ---------------- */
static float *g_temp = NULL;
static pid_t g_temp_pid = -1;

static void temp_start(void)
{
    g_temp = mmap(NULL, sizeof(float), PROT_READ | PROT_WRITE,
                  MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_temp == MAP_FAILED) { g_temp = NULL; return; }
    *g_temp = -999.0f;

    g_temp_pid = fork();
    if (g_temp_pid == 0) {
        int fd;
        /* 子进程必须恢复默认信号处理，否则会被父进程的 SIGTERM 处理器“吞掉”而杀不死 */
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT, SIG_DFL);
        signal(SIGHUP, SIG_DFL);
        /* 关闭从父进程继承的 video / fb / 日志句柄，否则会一直占着设备 */
        for (fd = 3; fd < 64; fd++) close(fd);

        fd = open("/dev/ds18b20", O_RDONLY);
        if (fd < 0) _exit(0);           /* 没有驱动就直接退出，父进程不显示温度 */
        for (;;) {
            int v = 0;
            if (read(fd, &v, sizeof(v)) == (ssize_t)sizeof(v))
                *g_temp = v / 10000.0f; /* 驱动给的是 0.0001℃，转成 ℃ */
            sleep(1);
        }
    }
}

static void temp_stop(void)
{
    if (g_temp_pid > 0) {
        kill(g_temp_pid, SIGTERM);
        waitpid(g_temp_pid, NULL, 0);
        g_temp_pid = -1;
    }
    if (g_temp) { munmap(g_temp, sizeof(float)); g_temp = NULL; }
}

/* 水印固定占用一块区域：像素转换时跳过它，否则每帧都会被画面覆盖 */
#define WM_X      8
#define WM_Y      8
#define WM_PAD    6
#define WM_SCALE  5
#define WM_MAXCH  8                                   /* 最长为 "T=-12.3C" */
#define WM_W      (WM_MAXCH * (5 * WM_SCALE + WM_SCALE) - WM_SCALE + WM_PAD * 2)
#define WM_H      (7 * WM_SCALE + WM_PAD * 2)

static void draw_watermark(void)
{
    char buf[24];
    int v, len;

    /* 先整块涂黑，保证字数变化时不残留上一帧的笔画 */
    fill_rect(WM_X, WM_Y, WM_W, WM_H, pack(0, 0, 0));

    if (!g_temp || *g_temp < -100.0f) return;

    v = (int)(*g_temp * 10.0f + 0.5f);  /* 保留 1 位小数 */
    if (v < 0) snprintf(buf, sizeof(buf), "T=-%d.%dC", (-v) / 10, (-v) % 10);
    else       snprintf(buf, sizeof(buf), "T=%d.%dC", v / 10, v % 10);

    len = (int)strlen(buf);
    if (len > WM_MAXCH) len = WM_MAXCH;

    draw_text(WM_X + WM_PAD, WM_Y + WM_PAD, buf, WM_SCALE, pack(255, 255, 255));
}

static int xioctl(int fd, int req, void *arg)
{
    int r;
    do { r = ioctl(fd, req, arg); } while (r == -1 && errno == EINTR);
    return r;
}

static double now_ms(void)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec * 1000.0 + tv.tv_usec / 1000.0;
}

/* 解绑 framebuffer 控制台：否则内核一打印日志，fbcon 重绘就会盖掉画面叠加内容 */
static void fbcon_off(void)
{
    int i, fd;
    char p[64];

    for (i = 0; i < 4; i++) {
        snprintf(p, sizeof(p), "/sys/class/vtconsole/vtcon%d/bind", i);
        fd = open(p, O_WRONLY);
        if (fd < 0) continue;
        write(fd, "0", 1);
        close(fd);
    }
}

static int fb_init(void)
{
    int fd;
    struct fb_var_screeninfo var;
    struct fb_fix_screeninfo fix;

    fd = open(FB_PATH, O_RDWR);
    if (fd < 0) { perror("open " FB_PATH); return -1; }

    if (xioctl(fd, FBIOGET_VSCREENINFO, &var) < 0) { perror("FBIOGET_VSCREENINFO"); close(fd); return -1; }
    if (xioctl(fd, FBIOGET_FSCREENINFO, &fix) < 0) { perror("FBIOGET_FSCREENINFO"); close(fd); return -1; }

    fb_w = var.xres; fb_h = var.yres;
    fb_bpp = var.bits_per_pixel;
    fb_line = fix.line_length;

    r_off = var.red.offset;   r_len = var.red.length;
    g_off = var.green.offset; g_len = var.green.length;
    b_off = var.blue.offset;  b_len = var.blue.length;

    fb_mem = mmap(NULL, fix.smem_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (fb_mem == MAP_FAILED) { perror("mmap fb"); return -1; }

    printf("fb: %dx%d %dbpp line=%d RGB(%d/%d,%d/%d,%d/%d)\n",
           fb_w, fb_h, fb_bpp, fb_line,
           r_off, r_len, g_off, g_len, b_off, b_len);
    return 0;
}

/* 在 /dev/videoN 中查找 UVC 设备 */
static int find_uvc(char *path, size_t len)
{
    int i, fd;
    struct v4l2_capability cap;

    for (i = 0; i < 12; i++) {
        snprintf(path, len, "/dev/video%d", i);
        fd = open(path, O_RDWR);
        if (fd < 0) continue;
        memset(&cap, 0, sizeof(cap));
        if (xioctl(fd, VIDIOC_QUERYCAP, &cap) == 0) {
            if (strstr((char *)cap.card, "USB") || strstr((char *)cap.driver, "uvcvideo")) {
                close(fd);
                return 0;
            }
        }
        close(fd);
    }
    return -1;
}

int main(int argc, char **argv)
{
    int vfd = -1;
    char devpath[64];
    struct v4l2_format fmt;
    struct v4l2_requestbuffers req;
    struct v4l2_buffer buf;
    struct vbuf bufs[REQ_BUFS];
    unsigned int sw = 0, sh = 0;
    unsigned int frames = 0;
    int timeouts = 0;
    double t_start = 0, t_prev = 0, worst = 0.0;
    int i;
    int *sxmap = NULL;
    struct sigaction sa;

    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_sig;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    if (argc > 1) {
        snprintf(devpath, sizeof(devpath), "%s", argv[1]);
    } else if (find_uvc(devpath, sizeof(devpath)) < 0) {
        fprintf(stderr, "未找到 UVC 摄像头，请手动指定设备，如 ./uvc2fb /dev/video3\n");
        return 1;
    }
    printf("video device: %s\n", devpath);

    vfd = open(devpath, O_RDWR);
    if (vfd < 0) { perror("open video"); return 1; }

    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = 640;
    fmt.fmt.pix.height = 480;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(vfd, VIDIOC_S_FMT, &fmt) < 0) {
        perror("VIDIOC_S_FMT");
        close(vfd);
        return 1;
    }
    if (fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV) {
        fprintf(stderr, "摄像头不支持 YUYV（当前 0x%08x），无法显示\n", fmt.fmt.pix.pixelformat);
        close(vfd);
        return 1;
    }
    sw = fmt.fmt.pix.width;
    sh = fmt.fmt.pix.height;
    printf("capture: %ux%u YUYV bytesperline=%u\n", sw, sh, fmt.fmt.pix.bytesperline);

    memset(&req, 0, sizeof(req));
    req.count = REQ_BUFS;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (xioctl(vfd, VIDIOC_REQBUFS, &req) < 0) { perror("VIDIOC_REQBUFS"); close(vfd); return 1; }

    for (i = 0; i < (int)req.count; i++) {
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (xioctl(vfd, VIDIOC_QUERYBUF, &buf) < 0) { perror("VIDIOC_QUERYBUF"); return 1; }
        bufs[i].length = buf.length;
        bufs[i].start = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, vfd, buf.m.offset);
        if (bufs[i].start == MAP_FAILED) { perror("mmap buf"); return 1; }
    }

    fbcon_off();    /* 关掉 framebuffer 控制台，防止内核日志刷掉画面 */
    if (fb_init() < 0) return 1;
    temp_start();   /* 启动温度后台读取，读不到就自动不显示 */

    /* 预计算横向映射表，避免每像素除法 */
    sxmap = malloc(sizeof(int) * fb_w);
    if (!sxmap) return 1;
    for (i = 0; i < fb_w; i++) {
        int sx = (int)((long)i * sw / fb_w);
        sxmap[i] = (sx & ~1) * 2;   /* 对齐到 YUYV 宏像素 */
    }

    for (i = 0; i < (int)req.count; i++) {
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (xioctl(vfd, VIDIOC_QBUF, &buf) < 0) { perror("VIDIOC_QBUF"); return 1; }
    }
    {
        int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        if (xioctl(vfd, VIDIOC_STREAMON, &type) < 0) { perror("VIDIOC_STREAMON"); return 1; }
    }
    printf("streaming... Ctrl-C 退出\n");
    t_start = t_prev = now_ms();

    while (g_run) {
        fd_set fds;
        struct timeval tv;
        int r;
        unsigned char *src;
        unsigned int y;

        FD_ZERO(&fds); FD_SET(vfd, &fds);
        tv.tv_sec = 2; tv.tv_usec = 0;
        r = select(vfd + 1, &fds, NULL, NULL, &tv);
        if (r <= 0) {
            /* 连续 6 次（约 12 秒）拿不到帧，判定断流，退出交给守护进程重启 */
            if (++timeouts >= 6) {
                fprintf(stderr, "连续 %d 次超时无画面，退出等待重启\n", timeouts);
                break;
            }
            continue;
        }
        timeouts = 0;

        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        if (xioctl(vfd, VIDIOC_DQBUF, &buf) < 0) {
            if (errno == EAGAIN) continue;
            perror("VIDIOC_DQBUF");
            break;
        }

        src = (unsigned char *)bufs[buf.index].start;

        for (y = 0; y < (unsigned int)fb_h; y++) {
            unsigned char *srow = src + (size_t)((y * sh / fb_h) * sw * 2);
            unsigned char *drow;
            int x;

            if (fb_bpp == 32)
                drow = fb_mem + (size_t)y * fb_line;
            else
                drow = fb_mem + (size_t)y * fb_line;

            for (x = 0; x < fb_w; x++) {
                int off = sxmap[x];
                int yy, uu, vv, c, d, e, rr, gg, bb;
                unsigned int px;

                /* 水印区域不参与转换，否则每帧都会被画面覆盖掉 */
                if (x >= WM_X && x < WM_X + WM_W &&
                    y >= (unsigned int)WM_Y && y < (unsigned int)(WM_Y + WM_H))
                    continue;

                yy = srow[off];
                uu = srow[off + 1];
                vv = srow[off + 3];
                c = yy - 16; d = uu - 128; e = vv - 128;
                rr = clip((298 * c + 409 * e + 128) >> 8);
                gg = clip((298 * c - 100 * d - 208 * e + 128) >> 8);
                bb = clip((298 * c + 516 * d + 128) >> 8);
                px = pack(rr, gg, bb);

                if (fb_bpp == 32)
                    ((unsigned int *)drow)[x] = px;
                else
                    ((unsigned short *)drow)[x] = (unsigned short)px;
            }
        }

        /* 在画面上叠加温度水印 */
        draw_watermark();

        if (xioctl(vfd, VIDIOC_QBUF, &buf) < 0) { perror("VIDIOC_QBUF"); break; }

        /* 统计帧率与最大帧间隔（抖动） */
        {
            double t_now = now_ms();
            double dt = t_now - t_prev;
            if (dt > worst) worst = dt;
            t_prev = t_now;

            frames++;
            if ((frames % 100) == 0) {
                double el = (t_now - t_start) / 1000.0;
                printf("frames=%u  avg=%.1f fps  worst=%.1f ms\n",
                       frames, frames / el, worst);
            }
        }
    }

    {
        int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        xioctl(vfd, VIDIOC_STREAMOFF, &type);
    }
    for (i = 0; i < (int)req.count; i++)
        if (bufs[i].start != MAP_FAILED) munmap(bufs[i].start, bufs[i].length);
    free(sxmap);
    temp_stop();
    close(vfd);
    printf("exit, total frames=%u  avg=%.1f fps  worst=%.1f ms\n",
           frames, frames / ((now_ms() - t_start) / 1000.0), worst);
    return 0;
}
