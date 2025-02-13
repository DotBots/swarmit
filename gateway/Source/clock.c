/**
 * @file
 * @ingroup bsp_clock
 *
 * @brief  nRF52833-specific definition of the "clock" bsp module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2022
 */
#include <nrf.h>
#include <stdbool.h>
#include "clock.h"

//=========================== defines ==========================================

typedef struct {
    bool hf_enabled;  ///< Checks whether high frequency clock is running
    bool lf_enabled;  ///< Checks whether low frequency clock is running
} clock_state_t;

//=========================== variables ========================================

static clock_state_t _clock_state = {
    .hf_enabled = false,
    .lf_enabled = false,
};

//=========================== public ===========================================

void hfclk_init(void) {
    if (_clock_state.hf_enabled) {
        // Do nothing if already running
        return;
    }

    NRF_CLOCK->EVENTS_HFCLKSTARTED = 0;
    while (NRF_CLOCK->EVENTS_HFCLKSTARTED == 1) {}

    NRF_CLOCK->TASKS_HFCLKSTART = 1;
    while (NRF_CLOCK->EVENTS_HFCLKSTARTED == 0) {}
    _clock_state.hf_enabled = true;
}

void lfclk_init(void) {
    if (_clock_state.lf_enabled) {
        // Do nothing if already running
        return;
    }

    NRF_CLOCK->EVENTS_LFCLKSTARTED = 0;
    NRF_CLOCK->LFCLKSRC = (CLOCK_LFCLKSRC_SRC_Xtal << CLOCK_LFCLKSRC_SRC_Pos);

    NRF_CLOCK->TASKS_LFCLKSTART = 1;
    while (NRF_CLOCK->EVENTS_LFCLKSTARTED == 0) {}
    _clock_state.lf_enabled = true;
}
