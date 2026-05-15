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
    int32_t homography_matrix[3][3];  ///< homography matrix, each element multiplied by 1e3
} localization_homography_t;

void localization_init(int32_t homographies[][3][3], uint32_t homography_count);

bool localization_process_data(void);

bool localization_get_position(position_2d_t *position);

#endif // __LOCALIZATION_H
