/*
 * uipad — synthetic gamepad for driving Leaf app UIs on the MLP1 over adb.
 *
 * Build and push with scripts/adb-uipad.sh; it runs on the device, not here.
 *
 * Two constraints are not optional, and both are silent when violated:
 *
 * 1. The device must exist BEFORE the app under test starts. SDL enumerates
 *    joysticks at init and does not pick up one that appears later, so a pad
 *    created afterwards is invisible to that process and the presses land in
 *    whatever else is running (usually the launcher, which then raises itself
 *    over the app). Hence --serve: create the pad once, keep it alive, feed it
 *    commands. Check the app log: "tracked (joystick)" is right.
 *
 * 2. It must clone the real Loong Gamepad identity (bus 0x0019, vendor 0x9903,
 *    product 0x9913, version 0x0102, name "Loong Gamepad"). SDL derives its
 *    GUID from those; with any other identity it opens the device as a mapped
 *    game controller instead of a raw joystick and renames the face buttons --
 *    "A" arrives as "B". The app log says "tracked (gamecontroller+joystick)"
 *    when this has happened. jawakad's own virtual pad clones the same identity
 *    for the same reason (Jawaka/internal/platform/input_proxy_mlp1.c).
 *
 * The 12 button codes below are exactly those the real pad declares, in
 * ascending order, which is the order SDL assigns button indices and therefore
 * matches Catastrophe's CAT__MLP1_BTN_* table.
 *
 *   uipad A                 press and release A
 *   uipad LEFT LEFT A       a sequence, in order
 *   uipad --hold 300 A      press, hold 300ms, release
 *   uipad --serve PATH      read space-separated buttons from a fifo until "quit"
 *
 * Buttons: A B X Y L1 R1 L2 R2 SELECT START MENU STICK UP DOWN LEFT RIGHT
 */
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <stdbool.h>

/* Ascending keycode order == SDL button index order. */
static const int keys[] = {
    BTN_SOUTH,  /* 0  B */
    BTN_EAST,   /* 1  A */
    BTN_NORTH,  /* 2  X */
    BTN_WEST,   /* 3  Y */
    BTN_TL,     /* 4  L1 */
    BTN_TR,     /* 5  R1 */
    BTN_TL2,    /* 6  L2 */
    BTN_TR2,    /* 7  R2 */
    BTN_SELECT, /* 8  */
    BTN_START,  /* 9  */
    BTN_MODE,   /* 10 MENU */
    BTN_THUMBL, /* 11 STICK */
};
#define NKEYS ((int)(sizeof(keys) / sizeof(keys[0])))

static struct { const char *name; int code; } named[] = {
    { "B", BTN_SOUTH }, { "A", BTN_EAST }, { "X", BTN_NORTH }, { "Y", BTN_WEST },
    { "L1", BTN_TL }, { "R1", BTN_TR }, { "L2", BTN_TL2 }, { "R2", BTN_TR2 },
    { "SELECT", BTN_SELECT }, { "START", BTN_START }, { "MENU", BTN_MODE },
    { "STICK", BTN_THUMBL },
};

static int fd;

static void emit(int type, int code, int val)
{
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.type = type; ev.code = code; ev.value = val;
    if (write(fd, &ev, sizeof(ev)) != (ssize_t)sizeof(ev))
        fprintf(stderr, "uipad: write failed\n");
}

static void syn(void) { emit(EV_SYN, SYN_REPORT, 0); }

static void msleep(int ms)
{
    struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

static void do_action(const char *a, int hold, int gap)
{
    if (!strcmp(a, "LEFT") || !strcmp(a, "RIGHT")) {
        int v = a[0] == 'L' ? -1 : 1;
        emit(EV_ABS, ABS_HAT0X, v); syn(); msleep(hold);
        emit(EV_ABS, ABS_HAT0X, 0); syn();
    } else if (!strcmp(a, "UP") || !strcmp(a, "DOWN")) {
        int v = a[0] == 'U' ? -1 : 1;
        emit(EV_ABS, ABS_HAT0Y, v); syn(); msleep(hold);
        emit(EV_ABS, ABS_HAT0Y, 0); syn();
    } else {
        int code = -1;
        for (int k = 0; k < (int)(sizeof(named) / sizeof(named[0])); k++)
            if (!strcmp(a, named[k].name)) { code = named[k].code; break; }
        if (code < 0) { fprintf(stderr, "uipad: unknown button %s\n", a); return; }
        emit(EV_KEY, code, 1); syn(); msleep(hold);
        emit(EV_KEY, code, 0); syn();
    }
    msleep(gap);
}

int main(int argc, char **argv)
{
    int hold = 60, settle = 700, gap = 220;

    fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) { perror("open /dev/uinput"); return 1; }

    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    for (int i = 0; i < NKEYS; i++) ioctl(fd, UI_SET_KEYBIT, keys[i]);
    ioctl(fd, UI_SET_EVBIT, EV_ABS);
    ioctl(fd, UI_SET_ABSBIT, ABS_X);
    ioctl(fd, UI_SET_ABSBIT, ABS_Y);
    ioctl(fd, UI_SET_ABSBIT, ABS_HAT0X);
    ioctl(fd, UI_SET_ABSBIT, ABS_HAT0Y);

    /* Mirror the Loong Gamepad exactly. The GUID SDL derives from
       bus/vendor/product/version decides whether it opens the device as a raw
       joystick or as a mapped game controller, and a mapped controller renames
       the face buttons -- which is how "A" arrived as "B" and quit the app.
       jawakad's own virtual pad clones the same identity. */
    struct uinput_setup us;
    memset(&us, 0, sizeof(us));
    us.id.bustype = 0x0019;   /* BUS_HOST, as the real pad reports */
    us.id.vendor  = 0x9903;
    us.id.product = 0x9913;
    us.id.version = 0x0102;
    snprintf(us.name, sizeof(us.name), "Loong Gamepad");
    ioctl(fd, UI_DEV_SETUP, &us);

    struct uinput_abs_setup abs;
    memset(&abs, 0, sizeof(abs));
    abs.absinfo.minimum = -1;
    abs.absinfo.maximum = 1;
    abs.code = ABS_HAT0X; ioctl(fd, UI_ABS_SETUP, &abs);
    abs.code = ABS_HAT0Y; ioctl(fd, UI_ABS_SETUP, &abs);
    abs.absinfo.minimum = -128; abs.absinfo.maximum = 127; abs.absinfo.flat = 15;
    abs.code = ABS_X; ioctl(fd, UI_ABS_SETUP, &abs);
    abs.code = ABS_Y; ioctl(fd, UI_ABS_SETUP, &abs);

    if (ioctl(fd, UI_DEV_CREATE) < 0) { perror("UI_DEV_CREATE"); return 1; }

    const char *serve_path = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--settle") && i + 1 < argc) settle = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--hold") && i + 1 < argc) hold = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gap") && i + 1 < argc) gap = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--serve") && i + 1 < argc) serve_path = argv[++i];
    }
    msleep(settle);

    /* Serve mode: the device must already exist when the app under test starts,
       because SDL enumerates joysticks once at init and never sees a pad that
       appears later. Create it first, launch the app, then feed it commands. */
    if (serve_path) {
        /* O_RDWR, not O_RDONLY: as a reader-only the fifo returns EOF every time
           the last writer closes, which is after every single send. Holding a
           write end ourselves keeps the stream open for the whole session and
           removes the need for a separate holder process. */
        int ffd = open(serve_path, O_RDWR);
        if (ffd < 0) { perror("open fifo"); return 1; }
        FILE *in = fdopen(ffd, "r");
        if (!in) { perror("fdopen"); return 1; }

        printf("ready\n");
        fflush(stdout);
        char line[256];
        while (fgets(line, sizeof(line), in)) {
            char *nl = strchr(line, '\n');
            if (nl) *nl = '\0';
            if (!line[0]) continue;
            if (!strcmp(line, "quit")) break;
            for (char *tok = strtok(line, " \t"); tok; tok = strtok(NULL, " \t"))
                do_action(tok, hold, gap);
        }
        msleep(200);
        ioctl(fd, UI_DEV_DESTROY);
        close(fd);
        return 0;
    }

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--settle") || !strcmp(a, "--hold") || !strcmp(a, "--gap") ||
            !strcmp(a, "--serve")) { i++; continue; }
        if (!strcmp(a, "--sleep")) { msleep(atoi(argv[++i])); continue; }
        do_action(a, hold, gap);
    }

    msleep(200);
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    return 0;
}
