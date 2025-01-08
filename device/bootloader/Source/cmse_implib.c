
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <nrf.h>

#include "cmse_implib.h"
#include "device.h"
#include "ipc.h"
#include "protocol.h"
#include "rng.h"

static uint8_t _tx_data_buffer[255];
extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

__attribute__((cmse_nonsecure_entry)) void swarmit_reload_wdt0(void) {
    NRF_WDT0_S->RR[0] = WDT_RR_RR_Reload << WDT_RR_RR_Pos;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_send_packet(const uint8_t *packet, uint8_t length) {
    protocol_header_to_buffer(_tx_data_buffer, BROADCAST_ADDRESS, DotBot, PROTOCOL_SWARMIT_PACKET);
    memcpy(_tx_data_buffer + sizeof(protocol_header_t), &packet, length);
    tdma_client_tx(_tx_data_buffer, sizeof(protocol_header_t) + length);
}

__attribute__((cmse_nonsecure_entry)) void swarmit_send_raw_data(const uint8_t *packet, uint8_t length) {
    tdma_client_tx(packet, length);
}

__attribute__((cmse_nonsecure_entry)) void swarmit_ipc_isr(ipc_isr_cb_t cb) {
    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX] = 0;
        cb((const uint8_t *)ipc_shared_data.data_pdu.buffer, ipc_shared_data.data_pdu.length);
    }
}

__attribute__((cmse_nonsecure_entry)) void swarmit_init_rng(void) {
    rng_init();
}

__attribute__((cmse_nonsecure_entry)) void swarmit_read_rng(uint8_t *value) {
    rng_read(value);
}

__attribute__((cmse_nonsecure_entry)) uint64_t swarmit_read_device_id(void) {
    return db_device_id();
}

__attribute__((cmse_nonsecure_entry)) void swarmit_log_data(uint8_t *data, size_t length) {
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
    NRF_IPC_S->TASKS_SEND[IPC_CHAN_LOG_EVENT] = 1;
}
