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
    puts("Store homography matrix");
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            printf("%i ", swrmt_homography[i][j]);
        }
        printf("\n");
    }
    // Only store the homography if a valid one is set in lh2_calibration.h
    db_lh2_store_homography(&_localization_data.lh2, 0, swrmt_homography);
#endif

}

bool localization_process_data(void) {
    db_lh2_process_location(&_localization_data.lh2);
    return (_localization_data.lh2.data_ready[0][0] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][0] == DB_LH2_PROCESSED_DATA_AVAILABLE);
}

bool localization_get_position(position_2d_t *position) {
    if ((LH2_CALIBRATION_IS_VALID) && (_localization_data.lh2.data_ready[0][0] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][0] == DB_LH2_PROCESSED_DATA_AVAILABLE)) {
        db_lh2_stop();
        db_lh2_calculate_position(_localization_data.lh2.locations[0][0].lfsr_counts, _localization_data.lh2.locations[1][0].lfsr_counts, _localization_data.lh2.locations[0][0].selected_polynomial, _localization_data.coordinates);
        if (_localization_data.coordinates[0] < 0 || _localization_data.coordinates[0] > 1.0 || _localization_data.coordinates[1] < 0 || _localization_data.coordinates[1] > 1) {
            printf("Invalid coordinates (%f,%f)\n", _localization_data.coordinates[0], _localization_data.coordinates[1]);
            db_lh2_start();
            return false;
        }

        uint32_t position_x = (uint32_t)(_localization_data.coordinates[0] * 1e6);
        uint32_t position_y = (uint32_t)(_localization_data.coordinates[1] * 1e6);

        if (position_x == UINT32_MAX || position_y == UINT32_MAX) {
            db_lh2_start();
            return false;
        }

        position->x = (uint32_t)(_localization_data.coordinates[0] * 1e6);
        position->y = (uint32_t)(_localization_data.coordinates[1] * 1e6);
        printf("Position (%u,%u)\n", position->x, position->y);
        db_lh2_start();
        return true;
    }

    return false;
}
