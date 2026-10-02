#ifndef __LH2_SELECT_H
#define __LH2_SELECT_H

/**
 * @brief   Per-station validity rectangles of an LH2 calibration
 *
 * No hardware calls, so the module also builds on the host.
 *
 * @{
 * @file
 * @copyright Inria, 2026
 * @}
 */

#include <stdbool.h>
#include <stdint.h>

#define LH2_SELECT_STATIONS         (16U)       ///< station indices 0 to 15
#define LH2_SELECT_RECT_LEN         (4U)        ///< x_min, y_min, x_max, y_max, mm
#define LH2_SELECT_RECT_MAX_DEFAULT (100000U)   ///< mm; x_max and y_max of the rectangle an all-0xFF one reads as

/// The rectangle a stored one stands for: all 0xFF is (0, 0, default, default)
void lh2_select_rect_resolve(const uint32_t stored[LH2_SELECT_RECT_LEN], uint32_t out[LH2_SELECT_RECT_LEN]);

/// The smallest rectangle holding the resolved rectangle of every station in mask; all zero for an empty mask
void lh2_select_rect_union(const uint32_t rects[LH2_SELECT_STATIONS][LH2_SELECT_RECT_LEN], uint32_t mask, uint32_t out[LH2_SELECT_RECT_LEN]);

/// Whether (x, y) is finite and inside rect, edges included
bool lh2_select_rect_contains(const uint32_t rect[LH2_SELECT_RECT_LEN], double x, double y);

#endif
