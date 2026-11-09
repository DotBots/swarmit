/**
 * @file
 * @brief  Per-station validity rectangles of an LH2 calibration
 *
 * @copyright Inria, 2026
 */
#include <string.h>

#include "lh2_select.h"

void lh2_select_rect_resolve(const uint32_t stored[LH2_SELECT_RECT_LEN], uint32_t out[LH2_SELECT_RECT_LEN]) {
    bool absent = true;
    for (uint8_t i = 0; i < LH2_SELECT_RECT_LEN; i++) {
        absent = absent && (stored[i] == UINT32_MAX);
    }
    if (absent) {
        out[0] = 0;
        out[1] = 0;
        out[2] = LH2_SELECT_RECT_MAX_DEFAULT;
        out[3] = LH2_SELECT_RECT_MAX_DEFAULT;
        return;
    }
    memcpy(out, stored, LH2_SELECT_RECT_LEN * sizeof(out[0]));
}

bool lh2_select_rect_contains(const uint32_t rect[LH2_SELECT_RECT_LEN], double x, double y) {
    // Every comparison with NaN is false, so a NaN coordinate is outside
    return x >= rect[0] && x <= rect[2] && y >= rect[1] && y <= rect[3];
}

void lh2_select_reset(lh2_select_best_t *best) {
    memset(best, 0, sizeof(*best));
}

bool lh2_select_offer(lh2_select_best_t *best, uint8_t station, double x, double y, const uint32_t rect[LH2_SELECT_RECT_LEN]) {
    if (!lh2_select_rect_contains(rect, x, y)) {
        return false;
    }
    double dx = x - 0.5 * ((double)rect[0] + (double)rect[2]);
    double dy = y - 0.5 * ((double)rect[1] + (double)rect[3]);
    double d2 = dx * dx + dy * dy;
    if (best->found && !(d2 < best->d2)) {
        return false;
    }
    best->found   = true;
    best->station = station;
    best->x       = x;
    best->y       = y;
    best->d2      = d2;
    return true;
}
