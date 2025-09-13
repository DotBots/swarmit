#ifndef __BATTERY_H
#define __BATTERY_H

/**
 * @defgroup    bsp_battery  Battery level measurement functions
 * @ingroup     bsp
 * @brief       Functions for measuring battery level
 *
 * @{
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2025
 * @}
 */

#include "saadc.h"

// For reading the battery level
#if defined(BOARD_DOTBOT_V3)
#define ROBOT_BATTERY_LEVEL_PIN     (DB_SAADC_INPUT_AIN1)
#else
#define ROBOT_BATTERY_LEVEL_PIN     (DB_SAADC_INPUT_VDD)
#endif

void battery_level_init(void);

uint16_t battery_level_read(void);

#endif // __BATTERY_H
