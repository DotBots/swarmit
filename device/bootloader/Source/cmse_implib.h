#ifndef __CMSE_IMPLIB_H
#define __CMSE_IMPLIB_H

/**
 * @defgroup    bsp_cmse_implib  CMSE secure gateway functions
 * @ingroup     bsp
 * @brief       Secure gateway functions for Non-Secure Callable functions
 *
 * @{
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2024
 * @}
 */

#include <stdint.h>
#include <stdlib.h>

#include "localization.h"

typedef void (*ipc_isr_cb_t)(const uint8_t *, size_t) __attribute__((cmse_nonsecure_call));

__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_keep_alive(void);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_send_data_packet(const uint8_t *packet, uint8_t length);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_send_raw_data(const uint8_t *packet, uint8_t length);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_ipc_isr(ipc_isr_cb_t cb);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_init_rng(void);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_read_rng(uint8_t *value);
__attribute__((cmse_nonsecure_entry, aligned)) uint64_t swarmit_read_device_id(void);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_log_data(uint8_t *data, size_t length);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_get_battery_level(uint16_t *battery);

/// Uplink packets per second x 100 this node gets on the schedule it joined
/// with (377 on huge); 0 when not joined.
__attribute__((cmse_nonsecure_entry, aligned)) uint16_t swarmit_get_uplink_budget(void);

// Lighthouse 2 functions exposed to user image
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_localization_get_position(position_2d_t *position);

/// Read the current position together with the sequence number of the solve it
/// came from. The sequence starts at 0 and advances by one per published solve,
/// so an unchanged sequence means the same measurement read twice, which
/// comparing coordinates cannot distinguish from a stationary robot.
__attribute__((cmse_nonsecure_entry, aligned)) uint32_t swarmit_localization_get_fix(position_2d_t *position);

/// Start LH2 if needed and drain the raw counts of every basestation with both
/// sweeps decoded into @p samples, at most @p max of them. Returns the number
/// written; 0 when none is ready, or the buffer is misaligned or not in
/// non-secure memory.
__attribute__((cmse_nonsecure_entry, aligned)) uint8_t swarmit_localization_get_raw_counts(lh2_raw_sample_t *samples, uint8_t max);
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_localization_handle_isr(void);

// SAADC functions
__attribute__((cmse_nonsecure_entry, aligned)) void swarmit_saadc_read(uint8_t channel, uint16_t *value);

#endif // __CMSE_IMPLIB_H
