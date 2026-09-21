#ifndef __LOCALIZATION_H
#define __LOCALIZATION_H

/**
 * @defgroup    bsp_localization  Localization functions
 * @ingroup     bsp
 * @brief       Functions for localization
 *
 * @{
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2025
 * @}
 */

#include <stdbool.h>
#include <stdint.h>

#define LH2_BASESTATION_COUNT_MAX (16)

/// DotBot protocol LH2 computed location
typedef struct __attribute__((packed)) {
    uint32_t x;  ///< X coordinate in mm
    uint32_t y;  ///< Y coordinate in mm
} position_2d_t;

typedef struct __attribute__((packed)) {
    uint8_t basestation_index;        ///< which LH basestation is this homography for?
    float   homography_matrix[3][3];  ///< homography matrix, float32 in mm
} localization_homography_t;

/// Raw LH2 LFSR counts for a single basestation (both sweeps), used for OTA calibration capture
typedef struct __attribute__((packed)) {
    uint8_t  lh_index;  ///< basestation index
    uint32_t count1;    ///< sweep 0 LFSR count
    uint32_t count2;    ///< sweep 1 LFSR count
} lh2_raw_sample_t;

/// Load the homographies and the rectangle outside which a solve is dropped
/// (x_min, y_min, x_max, y_max in mm; all 0xFF selects 0 to 100000 mm).
void localization_init(float homographies[][3][3], uint32_t homography_count, const uint32_t valid_mm[4]);

/// Start the LH2 driver without loading any calibration (idempotent). Used for raw capture in READY mode.
void localization_start(void);

bool localization_process_data(void);

bool localization_get_position(position_2d_t *position);

/// Drain the raw LFSR counts of every basestation that has both sweeps ready.
/// Returns the number of samples written to @p out (capped at @p max), clearing the consumed data_ready flags.
uint8_t localization_get_raw_counts(lh2_raw_sample_t *out, uint8_t max);

#endif // __LOCALIZATION_H
