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
#include <stddef.h>
#include <stdint.h>

#define LH2_BASESTATION_COUNT_MAX (16)

#define LH2_VALID_MM_LEN          (4U)       ///< x_min, y_min, x_max, y_max
#define LH2_VALID_MM_MAX_DEFAULT  (100000U)  ///< mm; x_max and y_max when the calibration carries no rectangle

/// DotBot protocol LH2 computed location
typedef struct __attribute__((packed)) {
    uint32_t x;  ///< X coordinate in mm
    uint32_t y;  ///< Y coordinate in mm
} position_2d_t;

/// The veneers store x and y as words, so a caller's position_2d_t must sit at this alignment.
#define POSITION_2D_ALIGN (4U)

typedef struct __attribute__((packed)) {
    uint8_t basestation_index;        ///< which LH basestation is this homography for?
    float   homography_matrix[3][3];  ///< homography matrix, float32 in mm
} localization_homography_t;

/// Raw LH2 LFSR counts for a single basestation (both sweeps), used for OTA calibration capture.
/// Naturally aligned: the secure side stores into it through a veneer with the
/// unaligned-access trap enabled, so the user image must pass a 4-byte-aligned buffer.
typedef struct {
    uint32_t count1;    ///< sweep 0 LFSR count
    uint32_t count2;    ///< sweep 1 LFSR count
    uint8_t  lh_index;  ///< basestation index
    uint8_t  _pad[3];
} lh2_raw_sample_t;

_Static_assert(sizeof(lh2_raw_sample_t) == 12, "lh2_raw_sample_t is part of the NSC ABI");
_Static_assert(offsetof(lh2_raw_sample_t, count1) == 0, "lh2_raw_sample_t is part of the NSC ABI");
_Static_assert(offsetof(lh2_raw_sample_t, count2) == 4, "lh2_raw_sample_t is part of the NSC ABI");
_Static_assert(offsetof(lh2_raw_sample_t, lh_index) == 8, "lh2_raw_sample_t is part of the NSC ABI");

/// Size of one sample on the wire: [lh_index:1][count1:4 LE][count2:4 LE]
#define LH2_RAW_SAMPLE_WIRE_SIZE (9U)

/// Load the homographies and the rectangle outside which a solve is dropped
/// (x_min, y_min, x_max, y_max in mm; all 0xFF selects 0 to LH2_VALID_MM_MAX_DEFAULT).
void localization_init(float homographies[][3][3], uint32_t homography_count, const uint32_t valid_mm[LH2_VALID_MM_LEN]);

/// Start the LH2 driver without loading any calibration (idempotent). Used for raw capture in READY mode.
void localization_start(void);

bool localization_process_data(void);

bool localization_get_position(position_2d_t *position);

/// Drain the raw LFSR counts of every basestation that has both sweeps ready.
/// Returns the number of samples written to @p out (capped at @p max), clearing the consumed data_ready flags.
uint8_t localization_get_raw_counts(lh2_raw_sample_t *out, uint8_t max);

#endif // __LOCALIZATION_H
