#include <stdio.h>
#include <string.h>

#include "board_config.h"
#include "lh2.h"
#include "localization.h"
#include "lh2_calibration.h"

typedef struct {
    db_lh2_t                lh2;
    double                  coordinates[2];
} localization_data_t;

static __attribute__((aligned(4))) localization_data_t _localization_data = { 0 };


void localization_init(void) {
    puts("Initialize localization");
    db_lh2_init(&_localization_data.lh2, &db_lh2_d, &db_lh2_e);
    db_lh2_start();

#if LH2_CALIBRATION_IS_VALID
    // Only store the homography if a valid one is set in lh2_calibration.h
    for (uint8_t lh_index = 0; lh_index < LH2_CALIBRATION_COUNT; lh_index++) {
        printf("Store homography matrix for LH%u:\n", lh_index);
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                printf("%i ", swrmt_homographies[lh_index][i][j]);
            }
            printf("\n");
        }
        db_lh2_store_homography(&_localization_data.lh2, lh_index, swrmt_homographies[lh_index]);
    }
#endif

}

bool localization_process_data(void) {
    db_lh2_process_location(&_localization_data.lh2);
    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT; lh_index++) {
        if (_localization_data.lh2.data_ready[0][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE) {
            return true;
        }
    }
    return false;
}

bool localization_get_position(position_2d_t *position) {
    if (LH2_CALIBRATION_IS_VALID) {
        db_lh2_stop();
        for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT; lh_index++) {
            if (_localization_data.lh2.data_ready[0][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE) {
                db_lh2_calculate_position(_localization_data.lh2.locations[0][lh_index].lfsr_counts, _localization_data.lh2.locations[1][lh_index].lfsr_counts, lh_index, _localization_data.coordinates);
                _localization_data.lh2.data_ready[0][lh_index] = DB_LH2_NO_NEW_DATA;
                _localization_data.lh2.data_ready[1][lh_index] = DB_LH2_NO_NEW_DATA;
                break;
            }
        }
        db_lh2_start();

        if (_localization_data.coordinates[0] < 0 || _localization_data.coordinates[0] > 100000 || _localization_data.coordinates[1] < 0 || _localization_data.coordinates[1] > 100000) {
            printf("Invalid coordinates (%f,%f)\n", _localization_data.coordinates[0], _localization_data.coordinates[1]);
            return false;
        }

        uint32_t position_x = (uint32_t)(_localization_data.coordinates[0]);
        uint32_t position_y = (uint32_t)(_localization_data.coordinates[1]);

        if (position_x == UINT32_MAX || position_y == UINT32_MAX) {
            return false;
        }

        position->x = (uint32_t)(_localization_data.coordinates[0]);
        position->y = (uint32_t)(_localization_data.coordinates[1]);
        printf("Position (%u,%u)\n", position->x, position->y);
        return true;
    }

    return false;
}
