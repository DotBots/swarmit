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
static float    _homographies[LH2_BASESTATION_COUNT_MAX][3][3] = { 0 };          ///< by slot, for the floor lines
static db_lh2_floor_line_t _lines[LH2_LINES_MAX];                                ///< ring of lines not yet drained
static uint8_t             _lines_head  = 0;                                     ///< next slot written
static uint8_t             _lines_count = 0;                                     ///< lines held
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
    printf("LH2 station mask 0x%04X\n", station_mask);
    localization_start();

    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT_MAX; lh_index++) {
        if (((station_mask >> lh_index) & 1U) == 0) {
            continue;
        }
        lh2_select_rect_resolve(valid_mm[lh_index], _valid_mm[lh_index]);
        printf("LH%u x [%u, %u] y [%u, %u] mm, H:\n", lh_index, _valid_mm[lh_index][0], _valid_mm[lh_index][2], _valid_mm[lh_index][1], _valid_mm[lh_index][3]);
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                printf("%f ", (double)homographies[lh_index][i][j]);
            }
            printf("\n");
        }
        db_lh2_store_homography(&_localization_data.lh2, lh_index, homographies[lh_index]);
        memcpy(_homographies[lh_index], homographies[lh_index], sizeof(_homographies[0]));
    }
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

/// Copy and clear both sweeps of a station when both are fresh
static bool _take_pair(uint8_t lh_index, uint32_t *count1, uint32_t *count2) {
    db_lh2_t *lh2 = &_localization_data.lh2;
    if (lh2->data_ready[0][lh_index] != DB_LH2_PROCESSED_DATA_AVAILABLE || lh2->data_ready[1][lh_index] != DB_LH2_PROCESSED_DATA_AVAILABLE) {
        return false;
    }
    db_lh2_stop();
    bool fresh = lh2->data_ready[0][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE && lh2->data_ready[1][lh_index] == DB_LH2_PROCESSED_DATA_AVAILABLE;
    if (fresh) {
        *count1                      = lh2->locations[0][lh_index].lfsr_counts;
        *count2                      = lh2->locations[1][lh_index].lfsr_counts;
        lh2->data_ready[0][lh_index] = DB_LH2_NO_NEW_DATA;
        lh2->data_ready[1][lh_index] = DB_LH2_NO_NEW_DATA;
    }
    db_lh2_start();
    return fresh;
}

_Static_assert(LH2_LINES_MAX % 2 == 0, "pairs never straddle the end of the ring");

/// Pairs go straight into the ring: the head is always even, and
/// db_lh2_sweep_lines() writes nothing when it fails
static void _lines_push(uint32_t count1, uint32_t count2, uint8_t lh_index) {
    if (db_lh2_sweep_lines(count1, count2, lh_index, (const float(*)[3])_homographies[lh_index], &_lines[_lines_head]) != 2) {
        return;
    }
    _lines_head  = (uint8_t)((_lines_head + 2) % LH2_LINES_MAX);
    _lines_count = (_lines_count + 2 > LH2_LINES_MAX) ? LH2_LINES_MAX : (uint8_t)(_lines_count + 2);
}

uint8_t localization_get_lines(db_lh2_floor_line_t *out, uint8_t max) {
    uint8_t n     = (max < _lines_count) ? max : _lines_count;
    uint8_t first = (uint8_t)((_lines_head + LH2_LINES_MAX - _lines_count) % LH2_LINES_MAX);
    for (uint8_t i = 0; i < n; i++) {
        out[i] = _lines[(first + i) % LH2_LINES_MAX];
    }
    _lines_count -= n;
    return n;
}

bool localization_get_position(position_2d_t *position) {
    if (_station_mask == 0) {
        return false;
    }

    lh2_select_best_t best;
    lh2_select_reset(&best);
    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT_MAX; lh_index++) {
        // Every fresh pair is taken, whatever its station, so none is used
        // stale by a later call; the decoder stops only for the copy
        uint32_t count1, count2;
        if (!_take_pair(lh_index, &count1, &count2)) {
            continue;
        }
        // A station without a homography would solve to NaN, or worse
        if (((_station_mask >> lh_index) & 1U) == 0) {
            continue;
        }
        db_lh2_calculate_position(count1, count2, lh_index, _localization_data.coordinates);
        double x = _localization_data.coordinates[0];
        double y = _localization_data.coordinates[1];
        if (!lh2_select_rect_contains(_valid_mm[lh_index], x, y)) {
            printf("LH%u (%f,%f) outside\n", lh_index, x, y);
            continue;
        }
        lh2_select_offer(&best, lh_index, x, y, _valid_mm[lh_index]);
        _lines_push(count1, count2, lh_index);
    }
    if (!best.found) {
        return false;
    }

    // Inside its station's rectangle, so within uint32
    _localization_data.position.x = (uint32_t)best.x;
    _localization_data.position.y = (uint32_t)best.y;
    position->x                   = _localization_data.position.x;
    position->y                   = _localization_data.position.y;
    printf("Position (%u,%u) from LH%u\n", position->x, position->y, best.station);
    return true;
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
