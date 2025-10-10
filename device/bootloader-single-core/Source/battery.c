#include <stdio.h>

#include "battery.h"

#include "saadc.h"

void battery_level_init(void) {
    db_saadc_init(DB_SAADC_RESOLUTION_12BIT);
}

uint16_t battery_level_read(void) {
    uint16_t value_12b = 0;
    db_saadc_read(ROBOT_BATTERY_LEVEL_PIN, &value_12b);
    uint16_t voltage_mv = (uint16_t)(((float)value_12b / 4095) * 3600);
    if (voltage_mv > BATTERY_LEVEL_MAX_MV) {
        voltage_mv = BATTERY_LEVEL_MAX_MV;
    }
    return voltage_mv;
}
