#include <stdio.h>
#include <string.h>

#include "board_config.h"
#include "lh2.h"
#include "localization.h"
#include "lh2_calibration.h"

_Static_assert(LH2_BASESTATION_COUNT_MAX == LH2_BASESTATION_COUNT, "localization.h and lh2.h must agree on the basestation ceiling");

/// Rectangle used when the calibration carries none. A solve outside the
/// rectangle is dropped; nothing else filters the stream.
static const uint32_t _valid_mm_default[LH2_VALID_MM_LEN] = { 0, 0, LH2_VALID_MM_MAX_DEFAULT, LH2_VALID_MM_MAX_DEFAULT };

typedef struct {
    db_lh2_t                lh2;
    double                  coordinates[2];
    position_2d_t           position;
} localization_data_t;

static __attribute__((aligned(4))) localization_data_t _localization_data = { 0 };
static bool _calibration_loaded = false;
static uint32_t _valid_mm[LH2_VALID_MM_LEN] = { 0, 0, LH2_VALID_MM_MAX_DEFAULT, LH2_VALID_MM_MAX_DEFAULT };
static bool _lh2_started = false;

void localization_start(void) {
    if (_lh2_started) {
        return;
    }
    db_lh2_init(&_localization_data.lh2, &db_lh2_d, &db_lh2_e);
    db_lh2_start();
    _lh2_started = true;
}

void localization_init(float homographies[][3][3], uint32_t homography_count, const uint32_t valid_mm[LH2_VALID_MM_LEN]) {
    printf("Initialize localization with %u homography matrices\n", homography_count);
    localization_start();

    bool valid_mm_absent = true;
    for (uint8_t i = 0; i < LH2_VALID_MM_LEN; i++) {
        valid_mm_absent = valid_mm_absent && (valid_mm[i] == UINT32_MAX);
    }
    memcpy(_valid_mm, valid_mm_absent ? _valid_mm_default : valid_mm, sizeof(_valid_mm));
    printf("Valid positions: x in [%u, %u], y in [%u, %u] mm\n", _valid_mm[0], _valid_mm[2], _valid_mm[1], _valid_mm[3]);

    for (uint8_t lh_index = 0; lh_index < homography_count; lh_index++) {
        printf("Store homography matrix for LH%u:\n", lh_index);
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                printf("%f ", (double)homographies[lh_index][i][j]);
            }
            printf("\n");
        }
        db_lh2_store_homography(&_localization_data.lh2, lh_index, homographies[lh_index]);
    }
    _calibration_loaded = (homography_count > 0);
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
    if (_calibration_loaded) {
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
        // Written as a negated conjunction so a NaN coordinate is rejected
        if (!(x >= _valid_mm[0] && x <= _valid_mm[2] && y >= _valid_mm[1] && y <= _valid_mm[3])) {
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
