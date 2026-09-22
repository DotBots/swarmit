#include <nrf.h>
#include <stdbool.h>
#include "ipc.h"

/**
 * @brief Variable in RAM containing the shared data structure
 */
volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

/**
 * @brief Lock the mutex, blocks until the mutex is locked
 */
void mutex_lock(void) {
    while (NRF_MUTEX_NS->MUTEX[0]) {}
}

/**
 * @brief Unlock the mutex, has no effect if the mutex is already unlocked
 */
void mutex_unlock(void) {
    NRF_MUTEX_NS->MUTEX[0] = 0;
}

/// Bound on the wait for the network core's ack. Its main loop normally
/// answers within one pass, well under a millisecond; this stays far below
/// the 1 s application watchdog even when a keep-alive is already overdue.
#define IPC_ACK_TIMEOUT_MS (100U)

/// Set when a request timed out and its ack has not been consumed yet.
static bool _ack_pending = false;

/// Secure SysTick as a one-shot countdown; the non-secure image has its own.
static void _timeout_start(uint32_t ms) {
    bool     hclk_128mhz = (NRF_CLOCK_S->HFCLKCTRL == (CLOCK_HFCLKCTRL_HCLK_Div1 << CLOCK_HFCLKCTRL_HCLK_Pos));
    uint32_t hz          = hclk_128mhz ? 128000000UL : 64000000UL;
    SysTick->LOAD        = (hz / 1000U) * ms - 1U;
    SysTick->VAL         = 0;
    SysTick->CTRL        = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_ENABLE_Msk;
}

static bool _timeout_expired(void) {
    return (SysTick->CTRL & SysTick_CTRL_COUNTFLAG_Msk) != 0;
}

static void _timeout_stop(void) {
    SysTick->CTRL = 0;
}

bool ipc_network_call(ipc_req_t req) {
    if (_ack_pending) {
        // The previous request is still outstanding until its ack shows up;
        // issuing another would overwrite what the network core is reading.
        if (!ipc_shared_data.net_ack) {
            ipc_shared_data.ipc_timeouts++;
            return false;
        }
        ipc_shared_data.net_ack = false;
        _ack_pending            = false;
    }
    if (req != IPC_REQ_NONE) {
        ipc_shared_data.req = req;
        __DMB();
        NRF_IPC_S->TASKS_SEND[IPC_CHAN_REQ] = 1;
    }
    _timeout_start(IPC_ACK_TIMEOUT_MS);
    while (!ipc_shared_data.net_ack) {
        if (_timeout_expired()) {
            _timeout_stop();
            _ack_pending = true;
            ipc_shared_data.ipc_timeouts++;
            return false;
        }
    }
    _timeout_stop();
    ipc_shared_data.net_ack = false;
    return true;
}

void release_network_core(void) {
    // Do nothing if network core is already started and ready
    if (!NRF_RESET_S->NETWORK.FORCEOFF && ipc_shared_data.net_ready) {
        return;
    } else if (!NRF_RESET_S->NETWORK.FORCEOFF) {
        ipc_shared_data.net_ready = false;
    }

    NRF_RESET_S->NETWORK.FORCEOFF = (RESET_NETWORK_FORCEOFF_FORCEOFF_Release << RESET_NETWORK_FORCEOFF_FORCEOFF_Pos);

    while (!ipc_shared_data.net_ready) {}
}
