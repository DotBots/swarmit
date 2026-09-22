
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <arm_cmse.h>
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
static __attribute__((aligned(4))) volatile uint32_t _localization_data_available = 0;

/// Counts the solves published to shared data. Wraps at 2^32, which at the
/// fastest sweep rate the sensor produces is several years of running.
static __attribute__((aligned(4))) uint32_t _localization_fix_sequence = 0;

extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

/// True when the caller may write [ptr, ptr + size) from non-secure state
/// and ptr is aligned to @p align. The TT lookup answers from the SPU, so a
/// secure peripheral alias, the PPB, secure flash and secure RAM all fail.
static bool _ns_writable(void *ptr, size_t size, size_t align) {
    return ((uintptr_t)ptr % align) == 0 && cmse_check_address_range(ptr, size, CMSE_NONSECURE | CMSE_MPU_READWRITE) != NULL;
}

/// True when the caller may read [ptr, ptr + size) from non-secure state.
static bool _ns_readable(const void *ptr, size_t size) {
    return size == 0 || cmse_check_address_range((void *)ptr, size, CMSE_NONSECURE | CMSE_MPU_READ) != NULL;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_keep_alive(void) {
    NRF_WDT0_S->RR[0] = WDT_RR_RR_Reload << WDT_RR_RR_Pos;
    ipc_shared_data.battery_level = battery_level_read();
    if (_localization_data_available) {
        // Cleared before the solve, not after: the SPIM4 handler can set it
        // again while localization_get_position() runs, and clearing on the way
        // out would drop that sweep.
        _localization_data_available = 0;
        position_2d_t position;
        if (!localization_get_position(&position)) {
            return;
        }
        mutex_lock();
        memcpy((void *)&ipc_shared_data.current_position, &position, sizeof(position_2d_t));
        _localization_fix_sequence++;
        mutex_unlock();
    }
}

/// Maps a TX request's outcome to the caller's result.
static swarmit_result_t _tx_result(bool acked) {
    if (!acked) {
        return SWARMIT_ERR_TIMEOUT;
    }
    return (ipc_shared_data.net_result == IPC_NET_NOT_JOINED) ? SWARMIT_ERR_NOT_JOINED : SWARMIT_OK;
}

__attribute__((cmse_nonsecure_entry)) swarmit_result_t swarmit_send_data_packet(const uint8_t *packet, uint8_t length) {
    if (length > sizeof(_tx_data_buffer) - 2 || !_ns_readable(packet, length)) {
        return SWARMIT_ERR_ARG;
    }
    size_t pos = 0;
    _tx_data_buffer[pos++] = PACKET_DATA;
    _tx_data_buffer[pos++] = length;
    memcpy(_tx_data_buffer + pos, packet, length);
    pos += length;
    return _tx_result(mari_node_tx(_tx_data_buffer, pos));
}

__attribute__((cmse_nonsecure_entry)) swarmit_result_t swarmit_send_raw_data(const uint8_t *packet, uint8_t length) {
    if (!_ns_readable(packet, length)) {
        return SWARMIT_ERR_ARG;
    }
    return _tx_result(mari_node_tx(packet, length));
}

__attribute__((cmse_nonsecure_entry)) void swarmit_ipc_isr(ipc_isr_cb_t cb) {
    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX] = 0;
        cb((const uint8_t *)ipc_shared_data.rx_pdu.buffer, ipc_shared_data.rx_pdu.length);
    }
}

__attribute__((cmse_nonsecure_entry)) swarmit_result_t swarmit_init_rng(void) {
    return rng_init() ? SWARMIT_OK : SWARMIT_ERR_TIMEOUT;
}

__attribute__((cmse_nonsecure_entry)) swarmit_result_t swarmit_read_rng(uint8_t *value) {
    if (!_ns_writable(value, sizeof(*value), __alignof__(*value))) {
        return SWARMIT_ERR_ARG;
    }
    return rng_read(value) ? SWARMIT_OK : SWARMIT_ERR_TIMEOUT;
}

__attribute__((cmse_nonsecure_entry)) uint64_t swarmit_read_device_id(void) {
    return db_device_id();
}

__attribute__((cmse_nonsecure_entry)) void swarmit_log_data(uint8_t *data, size_t length) {
    if (length > INT8_MAX || !_ns_readable(data, length)) {
        return;
    }

    mutex_lock();
    ipc_shared_data.log.length = length;
    memcpy((void *)ipc_shared_data.log.data, data, length);
    mutex_unlock();
    NRF_IPC_S->TASKS_SEND[IPC_CHAN_LOG_EVENT] = 1;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_get_battery_level(uint16_t *battery) {
    if (!_ns_writable(battery, sizeof(*battery), __alignof__(*battery))) {
        return;
    }
    *battery = ipc_shared_data.battery_level;
}

__attribute__((cmse_nonsecure_entry)) uint32_t swarmit_get_uplink_interval_us(void) {
    return ipc_shared_data.uplink.interval_us;
}

__attribute__((cmse_nonsecure_entry)) void swarmit_localization_get_position(position_2d_t *position) {
    if (!_ns_writable(position, sizeof(*position), POSITION_2D_ALIGN)) {
        return;
    }
    mutex_lock();
    position->x = ipc_shared_data.current_position.x;
    position->y = ipc_shared_data.current_position.y;
    mutex_unlock();
}

__attribute__((cmse_nonsecure_entry)) uint32_t swarmit_localization_get_fix(position_2d_t *position) {
    if (!_ns_writable(position, sizeof(*position), POSITION_2D_ALIGN)) {
        return 0;
    }
    mutex_lock();
    position->x        = ipc_shared_data.current_position.x;
    position->y        = ipc_shared_data.current_position.y;
    uint32_t sequence  = _localization_fix_sequence;
    mutex_unlock();
    return sequence;
}

__attribute__((cmse_nonsecure_entry)) uint8_t swarmit_localization_get_raw_counts(lh2_raw_sample_t *samples, uint8_t max) {
    if (max == 0 || !_ns_writable(samples, (size_t)max * sizeof(lh2_raw_sample_t), __alignof__(lh2_raw_sample_t))) {
        return 0;
    }

    localization_start();
    return localization_get_raw_counts(samples, max);
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
    if (!_ns_writable(value, sizeof(*value), __alignof__(*value))) {
        return;
    }
    return db_saadc_read(channel, value);
}
