#include <stdint.h>
#include <string.h>
#include <nrf.h>
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

void ipc_network_call(ipc_req_t req) {
    if (req != IPC_REQ_NONE) {
        ipc_shared_data.req                 = req;
        NRF_IPC_NS->TASKS_SEND[IPC_CHAN_REQ] = 1;
    }
    while (!ipc_shared_data.net_ack) {}
    ipc_shared_data.net_ack = false;
};

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

__attribute__((cmse_nonsecure_entry)) void log_data(uint8_t *data, size_t length) {
    if (length > INT8_MAX) {
        // Ensure length fits in the log data buffer in shared RAM
        return;
    }

    if ((data > (uint8_t *)0x20000000 && data < (uint8_t *)0x20008000) || (data > (uint8_t *)0x00000000 && data < (uint8_t *)0x00004000)) {
        // Ensure data address is not in secure space
        return;
    }

    ipc_shared_data.log.length = length;
    memcpy((void *)ipc_shared_data.log.data, data, length);
    NRF_IPC_NS->TASKS_SEND[IPC_CHAN_LOG_EVENT] = 1;
}
