
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <nrf.h>

#include "battery.h"
#include "cmse_implib.h"
#include "device.h"
#include "ipc.h"
#include "localization.h"
#include "mari.h"
#include "rng.h"
#include "lh2.h"
#include "saadc.h"

static __attribute__((aligned(4))) uint8_t _tx_data_buffer[UINT8_MAX];
static __attribute__((aligned(4))) uint32_t _localization_data_available = 0;

extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

__attribute__((cmse_nonsecure_entry)) void swarmit_keep_alive(void) {
    NRF_WDT0_S->RR[0] = WDT_RR_RR_Reload << WDT_RR_RR_Pos;
    ipc_shared_data.battery_level = battery_level_read();
    if (_localization_data_available) {
        position_2d_t position;
        if (!localization_get_position(&position)) {
            return;
        }
        mutex_lock();
        memcpy((void *)&ipc_shared_data.current_position, &position, sizeof(position_2d_t));
        mutex_unlock();
    }
}

__attribute__((cmse_nonsecure_entry)) void swarmit_send_data_packet(const uint8_t *packet, uint8_t length) {
    size_t pos = 0;
    _tx_data_buffer[pos++] = PACKET_DATA;
    _tx_data_buffer[pos++] = length;
    memcpy(_tx_data_buffer + pos, &packet, length);
    pos += length;
    mari_node_tx(_tx_data_buffer, pos);
}

__attribute__((cmse_nonsecure_entry)) void swarmit_send_raw_data(const uint8_t *packet, uint8_t length) {
    mari_node_tx(packet, length);
}

__attribute__((cmse_nonsecure_entry)) void swarmit_ipc_isr(ipc_isr_cb_t cb) {
    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX] = 0;
        cb((const uint8_t *)ipc_shared_data.rx_pdu.buffer, ipc_shared_data.rx_pdu.length);
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

    if ((data > (uint8_t *)0x20000000 && data < (uint8_t *)0x20008000) || (data > (uint8_t *)0x00000000 && data < (uint8_t *)0x0000ff00)) {
        // Ensure data address is not in secure space
        return;
    }

    mutex_lock();
    ipc_shared_data.log.length = length;
    memcpy((void *)ipc_shared_data.log.data, data, length);
    mutex_unlock();
    NRF_IPC_S->TASKS_SEND[IPC_CHAN_LOG_EVENT] = 1;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_get_battery_level(uint16_t *battery) {
    *battery = ipc_shared_data.battery_level;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_localization_get_position(position_2d_t *position) {
    mutex_lock();
    position->x = ipc_shared_data.current_position.x;
    position->y = ipc_shared_data.current_position.y;
    mutex_unlock();
}

__attribute__((cmse_nonsecure_entry)) void swarmit_localization_handle_isr(void) {
    if (NRF_SPIM4_S->EVENTS_END) {
        // Clear the Interrupt flag
        NRF_SPIM4_S->EVENTS_END = 0;
        db_lh2_handle_isr();
        _localization_data_available = localization_process_data();
    }
}

__attribute__((cmse_nonsecure_entry)) void swarmit_saadc_read(uint8_t channel, uint16_t *value) {
    if (channel != DB_SAADC_INPUT_VDDH && !(channel <= DB_SAADC_INPUT_VDD) && !(channel >= DB_SAADC_INPUT_AIN0)) {
        return;
    }
    return db_saadc_read(channel, value);
}
