#include <stdio.h>
#include <string.h>

#include "board_config.h"
#include "lh2.h"
#include "localization.h"
#include "lh2_calibration.h"
#include "lh2_select.h"

_Static_assert(LH2_BASESTATION_COUNT_MAX == LH2_BASESTATION_COUNT, "localization.h and lh2.h must agree on the basestation ceiling");
_Static_assert(LH2_BASESTATION_COUNT_MAX == LH2_SELECT_STATIONS, "lh2_select covers every basestation");
_Static_assert(LH2_VALID_MM_LEN == LH2_SELECT_RECT_LEN && LH2_VALID_MM_MAX_DEFAULT == LH2_SELECT_RECT_MAX_DEFAULT, "one rectangle layout");

typedef struct {
    db_lh2_t                lh2;
    double                  coordinates[2];
    position_2d_t           position;
} localization_data_t;

static __attribute__((aligned(4))) localization_data_t _localization_data = { 0 };
static uint32_t _station_mask = 0;
static uint32_t _valid_mm[LH2_BASESTATION_COUNT_MAX][LH2_VALID_MM_LEN] = { 0 };  ///< resolved, by slot
static uint32_t _fence[LH2_VALID_MM_LEN] = { 0 };                                ///< union of the rectangles in the mask
static bool _lh2_started = false;

void localization_start(void) {
    if (_lh2_started) {
        return;
    }
    db_lh2_init(&_localization_data.lh2, &db_lh2_d, &db_lh2_e);
    db_lh2_start();
    _lh2_started = true;
}

void localization_init(float homographies[][3][3], uint32_t station_mask, const uint32_t valid_mm[][LH2_VALID_MM_LEN]) {
    station_mask &= (1U << LH2_BASESTATION_COUNT_MAX) - 1U;
    printf("Initialize localization with station mask 0x%04X\n", station_mask);
    localization_start();

    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT_MAX; lh_index++) {
        if (((station_mask >> lh_index) & 1U) == 0) {
            continue;
        }
        lh2_select_rect_resolve(valid_mm[lh_index], _valid_mm[lh_index]);
        printf("Store homography matrix for LH%u, valid x in [%u, %u], y in [%u, %u] mm:\n", lh_index, _valid_mm[lh_index][0], _valid_mm[lh_index][2], _valid_mm[lh_index][1], _valid_mm[lh_index][3]);
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                printf("%f ", (double)homographies[lh_index][i][j]);
            }
            printf("\n");
        }
        db_lh2_store_homography(&_localization_data.lh2, lh_index, homographies[lh_index]);
    }
    lh2_select_rect_union(_valid_mm, station_mask, _fence);
    _station_mask = station_mask;
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
    if (_station_mask != 0) {
        bool solved = false;
        db_lh2_stop();
        for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT; lh_index++) {
            if (_localization_data.lh2.data_ready[0][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE) {
                db_lh2_calculate_position(_localization_data.lh2.locations[0][lh_index].lfsr_counts, _localization_data.lh2.locations[1][lh_index].lfsr_counts, lh_index, _localization_data.coordinates);
                _localization_data.lh2.data_ready[0][lh_index] = DB_LH2_NO_NEW_DATA;
                _localization_data.lh2.data_ready[1][lh_index] = DB_LH2_NO_NEW_DATA;
                solved = true;
                break;
            }
        }
        db_lh2_start();

        // No basestation had both sweeps decoded: coordinates[] still holds
        // the previous solve (zero before the first), which must not be
        // published under a new sequence number.
        if (!solved) {
            return false;
        }

        double x = _localization_data.coordinates[0];
        double y = _localization_data.coordinates[1];
        if (!lh2_select_rect_contains(_fence, x, y)) {
            printf("Invalid position (%f,%f)\n", _localization_data.coordinates[0], _localization_data.coordinates[1]);
            return false;
        }

        _localization_data.position.x = (uint32_t)_localization_data.coordinates[0];
        _localization_data.position.y = (uint32_t)_localization_data.coordinates[1];

        position->x = _localization_data.position.x;
        position->y = _localization_data.position.y;
        printf("Position (%u,%u)\n", position->x, position->y);
        return true;
    }

    return false;
}

uint8_t localization_get_raw_counts(lh2_raw_sample_t *out, uint8_t max) {
    uint8_t n = 0;
    db_lh2_stop();
    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT && n < max; lh_index++) {
        if (_localization_data.lh2.data_ready[0][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE && _localization_data.lh2.data_ready[1][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE) {
            out[n].lh_index = lh_index;
            out[n].count1   = _localization_data.lh2.locations[0][lh_index].lfsr_counts;
            out[n].count2   = _localization_data.lh2.locations[1][lh_index].lfsr_counts;
            _localization_data.lh2.data_ready[0][lh_index] = DB_LH2_NO_NEW_DATA;
            _localization_data.lh2.data_ready[1][lh_index] = DB_LH2_NO_NEW_DATA;
            n++;
        }
    }
    db_lh2_start();
    return n;
}
