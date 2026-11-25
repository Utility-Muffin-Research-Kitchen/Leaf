/* power-request: Jawaka's power handoff writer (internal/platform/
   power_request.h, the source of truth) as a command, so the session tests
   drive the real code rather than a copy of it.

     power-request available
     power-request publish poweroff|reboot
     power-request reason REASON
     power-request complete
     power-request incomplete <RECORD     (the record on stdin)

   Exit 0 on success, 1 when Jawaka's call refused, 2 on bad usage. */
#include "internal/platform/power_request.h"

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *cmd = argv[1];
    if (strcmp(cmd, "available") == 0 && argc == 2)
        return jw_power_request_available() ? 0 : 1;
    if (strcmp(cmd, "publish") == 0 && argc == 3)
        return jw_power_request_publish(argv[2]) == 0 ? 0 : 1;
    if (strcmp(cmd, "reason") == 0 && argc == 3)
        return jw_power_request_reason(argv[2]) == 0 ? 0 : 1;
    if (strcmp(cmd, "complete") == 0 && argc == 2)
        return jw_power_request_complete() == 0 ? 0 : 1;
    if (strcmp(cmd, "incomplete") == 0 && argc == 2) {
        char record[4096];
        size_t n = fread(record, 1, sizeof(record) - 1, stdin);
        record[n] = '\0';
        return jw_power_request_incomplete(record) == 0 ? 0 : 1;
    }
    return 2;
}
