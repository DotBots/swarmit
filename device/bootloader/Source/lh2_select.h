#ifndef __LH2_SELECT_H
#define __LH2_SELECT_H

/**
 * @brief   Per-station validity rectangles of an LH2 calibration, and the
 *          choice of one station's solve per fix
 *
 * Of the solves offered for one fix, a non-finite one or one outside its own
 * station's rectangle is dropped, and of the rest the one nearest its
 * station's rectangle centre is kept; on a tie the one offered first stays,
 * so offering in index order keeps the lower index.
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

/// Whether (x, y) is finite and inside rect, edges included
bool lh2_select_rect_contains(const uint32_t rect[LH2_SELECT_RECT_LEN], double x, double y);

/// The solve kept so far for one fix
typedef struct {
    bool    found;      ///< a solve has been kept
    uint8_t station;    ///< its station
    double  x;          ///< mm
    double  y;          ///< mm
    double  d2;         ///< squared distance to its station's rectangle centre, mm^2
} lh2_select_best_t;

/// Start a fix with nothing kept
void lh2_select_reset(lh2_select_best_t *best);

/// Offer one station's solve; returns whether it is now the one kept
bool lh2_select_offer(lh2_select_best_t *best, uint8_t station, double x, double y, const uint32_t rect[LH2_SELECT_RECT_LEN]);

#endif
