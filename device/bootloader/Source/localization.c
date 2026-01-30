#include <stdio.h>
#include <string.h>
#include <math.h>

#include "board_config.h"
#include "lh2.h"
#include "localization.h"
#include "lh2_calibration.h"

#define VALID_POSITION_DISTANCE_THRESHOLD_MM 500.0f  ///< Maximum distance in mm between two consecutive position measurements for the position to be considered valid

typedef struct {
    db_lh2_t                lh2;
    double                  coordinates[2];
    position_2d_t           position;
    position_2d_t           previous_position;
} localization_data_t;

static __attribute__((aligned(4))) localization_data_t _localization_data = { 0 };

float _distance(position_2d_t *reference, position_2d_t *current) {
    float dx = ((float)current->x - (float)reference->x);
    float dy = ((float)current->y - (float)reference->y);
    return sqrtf(powf(dx, 2) + powf(dy, 2));
}

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
            printf("Invalid position (%u,%u)\n", _localization_data.position.x, _localization_data.position.y);
            return false;
        }

        _localization_data.position.x = (uint32_t)_localization_data.coordinates[0];
        _localization_data.position.y = (uint32_t)_localization_data.coordinates[1];

        if (_localization_data.previous_position.x == 0 && _localization_data.previous_position.y == 0) {
            _localization_data.previous_position.x = _localization_data.position.x;
            _localization_data.previous_position.y = _localization_data.position.y;
        }

        float distance = _distance((position_2d_t *)&_localization_data.previous_position, (position_2d_t *)&_localization_data.position);
        if (distance > VALID_POSITION_DISTANCE_THRESHOLD_MM) {
            printf("Distance (%f) from (%u,%u) to (%u,%u) is too high\n",
                    distance,
                   _localization_data.previous_position.x,
                   _localization_data.previous_position.y,
                   _localization_data.position.x,
                   _localization_data.position.y);
            return false;
        }

        _localization_data.previous_position.x = _localization_data.position.x;
        _localization_data.previous_position.y = _localization_data.position.y;
        position->x = _localization_data.position.x;
        position->y = _localization_data.position.y;
        printf("Position (%u,%u)\n", position->x, position->y);
        return true;
    }

    return false;
}
