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

void lh2_select_rect_union(const uint32_t rects[LH2_SELECT_STATIONS][LH2_SELECT_RECT_LEN], uint32_t mask, uint32_t out[LH2_SELECT_RECT_LEN]) {
    bool any = false;
    memset(out, 0, LH2_SELECT_RECT_LEN * sizeof(out[0]));
    for (uint8_t i = 0; i < LH2_SELECT_STATIONS; i++) {
        if (((mask >> i) & 1U) == 0) {
            continue;
        }
        uint32_t r[LH2_SELECT_RECT_LEN];
        lh2_select_rect_resolve(rects[i], r);
        if (!any) {
            memcpy(out, r, sizeof(r));
            any = true;
            continue;
        }
        out[0] = (r[0] < out[0]) ? r[0] : out[0];
        out[1] = (r[1] < out[1]) ? r[1] : out[1];
        out[2] = (r[2] > out[2]) ? r[2] : out[2];
        out[3] = (r[3] > out[3]) ? r[3] : out[3];
    }
}

bool lh2_select_rect_contains(const uint32_t rect[LH2_SELECT_RECT_LEN], double x, double y) {
    // Every comparison with NaN is false, so a NaN coordinate is outside
    return x >= rect[0] && x <= rect[2] && y >= rect[1] && y <= rect[3];
}
