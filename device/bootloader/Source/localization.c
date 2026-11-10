#include <stdint.h>
#include <stdio.h>

#include "board_config.h"
#include "gpio.h"
#include "lh2.h"
#include "lh2_decoder.h"
#include "lh2_select.h"
#include "localization.h"
#include "timer_hf.h"

_Static_assert(LH2_BASESTATION_COUNT_MAX == DB_LH2_STATIONS, "localization.h and lh2_decoder.h must agree on the basestation ceiling");
_Static_assert(LH2_BASESTATION_COUNT_MAX == DB_LH2_SELECT_STATIONS, "lh2_select covers every basestation");
_Static_assert(LH2_VALID_MM_LEN == DB_LH2_SELECT_RECT_LEN && LH2_VALID_MM_MAX_DEFAULT == DB_LH2_SELECT_RECT_MAX_DEFAULT, "one rectangle layout");
_Static_assert(LH2_LINES_MAX == DB_LH2_SELECT_LINES_MAX, "one ring size");

typedef struct {
    db_lh2_decoder_t        decoder;
    position_2d_t           position;
} localization_data_t;

static __attribute__((aligned(4))) localization_data_t _localization_data = { 0 };
static db_lh2_select_conf_t _select_conf = { 0 };  ///< the calibration, by station
static db_lh2_lines_t       _lines       = { 0 };  ///< floor lines not yet drained
static bool _lh2_started = false;
static bool _lh2_sensor_ok = false;

static int32_t _clamp_mm(double v) {
    return (v > INT32_MAX) ? INT32_MAX : ((v < INT32_MIN) ? INT32_MIN : (int32_t)v);
}

#define LH2_POWER_CYCLES  (3U)       ///< init retries, each after an LH-EN power cycle
#define LH2_POWER_OFF_US  (100000U)
#define LH2_POWER_ON_US   (10000U)

#if defined(BOARD_DOTBOT_V3)
/// The TS4231 supply switch. db_lh2_capture_init drives the same pin high: keep the two in step.
static const gpio_t _lh2_en = { .port = 0, .pin = 16 };
#endif

/// The timer db_lh2_capture_init initialises and delays on (LH2_TIMER_DEV in lh2_default.c): keep in step.
#if defined(NRF5340_XXAA) && defined(NRF_APPLICATION)
#define LH2_DRIVER_TIMER_DEV (2)
#else
#define LH2_DRIVER_TIMER_DEV (3)
#endif

static bool _lh2_init(void) {
    if (db_lh2_capture_init(&db_lh2_d, &db_lh2_e)) {
        return true;
    }
#if defined(BOARD_DOTBOT_V3)
    // The TS4231 can latch a state its configuration sequence does not clear
    // across a soft reset; dropping its supply does.
    db_timer_hf_init(LH2_DRIVER_TIMER_DEV);
    for (uint32_t cycle = 1; cycle <= LH2_POWER_CYCLES; cycle++) {
        db_gpio_init(&db_lh2_d, DB_GPIO_IN);
        db_gpio_init(&db_lh2_e, DB_GPIO_IN);
        db_gpio_init(&_lh2_en, DB_GPIO_OUT);
        db_gpio_clear(&_lh2_en);
        db_timer_hf_delay_us(LH2_DRIVER_TIMER_DEV, LH2_POWER_OFF_US);
        db_gpio_set(&_lh2_en);
        db_timer_hf_delay_us(LH2_DRIVER_TIMER_DEV, LH2_POWER_ON_US);
        if (db_lh2_capture_init(&db_lh2_d, &db_lh2_e)) {
            printf("LH2 sensor recovered after %u power cycle(s)\n", (unsigned)cycle);
            return true;
        }
    }
#endif
    puts("LH2 sensor failed");
    return false;
}

bool localization_start(void) {
    if (_lh2_started) {
        return _lh2_sensor_ok;
    }
    db_lh2_decoder_init(&_localization_data.decoder);
    _lh2_sensor_ok = _lh2_init();
    if (_lh2_sensor_ok) {
        db_lh2_capture_start();
    }
    _lh2_started = true;
    return _lh2_sensor_ok;
}

bool localization_init(float homographies[][3][3], uint32_t station_mask, const uint32_t valid_mm[][LH2_VALID_MM_LEN]) {
    station_mask &= (1U << LH2_BASESTATION_COUNT_MAX) - 1U;
    printf("LH2 station mask 0x%04X\n", station_mask);
    bool sensor_ok = localization_start();

    db_lh2_select_conf_load(&_select_conf, station_mask, (const float(*)[3][3])homographies, valid_mm);
    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT_MAX; lh_index++) {
        if (((station_mask >> lh_index) & 1U) == 0) {
            continue;
        }
        const uint32_t *rect = _select_conf.rect_mm[lh_index];
        printf("LH%u x [%u, %u] y [%u, %u] mm, H:\n", lh_index, rect[0], rect[2], rect[1], rect[3]);
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                printf("%f ", (double)homographies[lh_index][i][j]);
            }
            printf("\n");
        }
    }
    return sensor_ok;
}

bool localization_process_data(void) {
    db_lh2_capture_t capture;
    if (db_lh2_capture_pop(&capture)) {
        db_lh2_decoder_feed(&_localization_data.decoder, &capture, db_lh2_capture_now_us());
    }
    for (uint8_t lh_index = 0; lh_index < DB_LH2_STATIONS; lh_index++) {
        if (db_lh2_decoder_pair_ready(&_localization_data.decoder, lh_index)) {
            return true;
        }
    }
    return false;
}

/// Take both sweeps of a station when both are fresh; the decoder stops only for the copy
static bool _take_pair(uint8_t lh_index, db_lh2_pair_t *pair) {
    if (!db_lh2_decoder_pair_ready(&_localization_data.decoder, lh_index)) {
        return false;
    }
    db_lh2_capture_stop();
    bool fresh = db_lh2_decoder_take_pair(&_localization_data.decoder, lh_index, pair);
    db_lh2_capture_start();
    return fresh;
}

uint8_t localization_get_lines(db_lh2_floor_line_t *out, uint8_t max) {
    return db_lh2_lines_drain(&_lines, out, max);
}

bool localization_get_position(position_2d_t *position) {
    if (_select_conf.station_mask == 0) {
        return false;
    }

    db_lh2_fix_t fix;
    db_lh2_select_begin(&fix);
    for (uint8_t lh_index = 0; lh_index < LH2_BASESTATION_COUNT_MAX; lh_index++) {
        // Every fresh pair is taken, whatever its station, so none is used
        // stale by a later call
        db_lh2_pair_t pair;
        if (!_take_pair(lh_index, &pair)) {
            continue;
        }
        double xy[2];
        switch (db_lh2_select_offer_pair(&_select_conf, &fix, &_lines, &pair, xy)) {
            case DB_LH2_SELECT_NOT_FINITE:
                printf("LH%u solve not finite\n", lh_index);
                break;
            case DB_LH2_SELECT_OUTSIDE:
                printf("LH%u (%ld,%ld) outside\n", lh_index, (long)_clamp_mm(xy[0]), (long)_clamp_mm(xy[1]));
                break;
            default:
                break;
        }
    }
    if (!fix.found) {
        return false;
    }

    // Inside its station's rectangle, so within uint32
    _localization_data.position.x = (uint32_t)fix.x_mm;
    _localization_data.position.y = (uint32_t)fix.y_mm;
    position->x                   = _localization_data.position.x;
    position->y                   = _localization_data.position.y;
    printf("Position (%u,%u) from LH%u\n", position->x, position->y, fix.station);
    return true;
}

uint8_t localization_get_raw_counts(lh2_raw_sample_t *out, uint8_t max) {
    uint8_t       n = 0;
    db_lh2_pair_t pair;
    db_lh2_capture_stop();
    // One pair per call keeps a single pair on the secure stack; each call
    // takes the lowest station still ready, so the order is the walk's
    while (n < max && db_lh2_select_take_pairs(&_localization_data.decoder, &pair, 1) == 1) {
        out[n].lh_index = pair.station;
        out[n].count1   = pair.count[0];
        out[n].count2   = pair.count[1];
        n++;
    }
    db_lh2_capture_start();
    return n;
}
