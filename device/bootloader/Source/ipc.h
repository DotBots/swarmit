#ifndef __IPC_H
#define __IPC_H

/**
 * @defgroup    bsp_ipc Inter-Processor Communication
 * @ingroup     bsp
 * @brief       Control the IPC peripheral (nRF53 only)
 *
 * @{
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2023
 * @}
 */

#include <nrf.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "localization.h"
#include "protocol.h"

#define IPC_IRQ_PRIORITY (1)

typedef enum {
    IPC_REQ_NONE,        ///< Sorry, but nothing
    IPC_MARI_INIT_REQ,
    IPC_MARI_NODE_TX_REQ,
    IPC_RNG_INIT_REQ,                ///< Request for rng init
    IPC_RNG_READ_REQ,                ///< Request for rng read
} ipc_req_t;

typedef enum {
    IPC_CHAN_REQ                = 0,    ///< Channel used for request events
    IPC_CHAN_RADIO_RX           = 1,    ///< Channel used for radio RX events
    IPC_CHAN_APPLICATION_START  = 2,    ///< Channel used for starting the application
    IPC_CHAN_APPLICATION_STOP   = 3,    ///< Channel used for stopping the application
    IPC_CHAN_SOC_RESET          = 4,    ///< Channel used to request a full SoC reset (e.g. after calibration commit)
    IPC_CHAN_LOG_EVENT          = 5,    ///< Channel used for logging events
    IPC_CHAN_OTA_START          = 6,    ///< Channel used for starting an OTA process
    IPC_CHAN_OTA_CHUNK          = 7,    ///< Channel used for writing a non secure image chunk
    IPC_CHAN_CALIBRATION_DATA   = 8,    ///< Channel used for sending calibration data
    IPC_CHAN_LH2_CAPTURE        = 9,    ///< Channel used to trigger a raw LH2 capture (READY mode only)
    IPC_CHAN_OTA_FINALIZE       = 10,   ///< Channel used to verify the whole image SHA256 (block OTA)
} ipc_channels_t;

typedef struct __attribute__((packed)) {
    uint8_t length;
    uint8_t data[INT8_MAX];
} ipc_log_data_t;

/// Shared memory only, never serialized: unpacked so the compiler keeps its
/// size a multiple of 4 and the members after it stay word-aligned.
typedef struct {
    uint32_t image_size;
    uint32_t chunk_count;
    uint32_t chunk_index;
    uint32_t chunk_size;
    int32_t  last_chunk_seen;                             ///< Last chunk index the net core published (-1 = none)
    uint32_t block_index;                                 ///< Current block being received
    uint32_t received_mask;                               ///< Bit i set: chunk block_index*W+i written to flash
    uint8_t  finalize_expected[SWRMT_OTA_SHA256_LENGTH];  ///< Expected whole-image SHA256 (FINALIZE)
    uint8_t  finalize_ok;                                 ///< FINALIZE result (1 = image SHA256 matched)
    uint8_t chunk[INT8_MAX + 1];
    char     pending_name[SWRMT_INFO_STRING_LEN];         ///< image_name from OTA_START, promoted to the device record on verified finalize
    char     pending_version[SWRMT_INFO_STRING_LEN];      ///< image_version from OTA_START, promoted the same way
} ipc_ota_data_t;

/// What this bot is running: the inventory the host reads once and caches.
/// The app core owns everything derived from the flash record; the net core
/// owns its own version string and the LH2 fields it loads from the config
/// page. Shared memory only, never serialized: unpacked so the compiler keeps
/// its size a multiple of 4 and the members after it stay word-aligned.
typedef struct {
    uint32_t boot_count;
    uint32_t image_size;
    uint8_t  image_digest[SWRMT_IMAGE_DIGEST_LEN];
    char     image_name[SWRMT_INFO_STRING_LEN];
    char     image_version[SWRMT_INFO_STRING_LEN];
    char     bl_version[SWRMT_INFO_STRING_LEN];     ///< app core writes
    char     net_version[SWRMT_INFO_STRING_LEN];    ///< net core writes
    uint8_t  info_gen;                              ///< bumped on boot and on OTA finalize; the host refetches on any change
    uint8_t  image_state;                           ///< swrmt_image_state_t
    uint8_t  image_result;                          ///< swrmt_image_result_t
    uint8_t  lh2_homography_count;                  ///< net core writes
    uint8_t  lh2_flags;                             ///< net core writes
} ipc_device_info_t;

typedef struct __attribute__((packed)) {
    uint32_t homography_count; // number of homography matrices used for localization
    float    homographies[LH2_BASESTATION_COUNT_MAX][3][3]; // homography matrices for localization, float32 in mm
} ipc_lh2_calibration_t;

typedef struct {
    uint8_t value;  ///< Byte containing the random value read
} ipc_rng_data_t;

typedef struct __attribute__((packed)) {
    uint8_t length;             ///< Length of the pdu in bytes
    uint8_t buffer[UINT8_MAX];  ///< Buffer containing the pdu data
} ipc_radio_pdu_t;

/// Crash report describing the most recent reset, appended to status frames
typedef struct __attribute__((packed)) {
    uint32_t reset_reason;  ///< RESETREAS value captured at boot (0 means power-on)
    uint8_t  fault;         ///< Fault latched before the reset (0: none, 1: hard fault, 2: secure fault)
    uint8_t  from_ns;       ///< 1 = non-secure user app faulted (resolve pc/lr against the app .elf); 0 = secure bootloader
    uint32_t cfsr;          ///< Configurable Fault Status Register at fault
    uint32_t sfsr;          ///< Secure Fault Status Register at fault
    uint32_t pc;            ///< Stacked program counter at fault
    uint32_t lr;            ///< Stacked link register at fault
    uint32_t sp;            ///< Stack pointer of the interrupted context (its exception frame address)
    uint32_t psr;           ///< Stacked xPSR; IPSR field names the active exception, 0 for thread mode
} ipc_crash_report_t;

typedef struct __attribute__((packed,aligned(8))) {
    bool                    net_ready;          ///< Network core is ready
    bool                    net_ack;            ///< Network core acked the latest request
    ipc_req_t               req;                ///< IPC network request
    uint8_t                 status;             ///< Experiment status
    uint16_t                battery_level;      ///< Battery level in mV
    swrmt_device_type_t     device_type;        ///< Device type
    ipc_log_data_t          log;                ///< Log data
    ipc_rng_data_t          rng;                ///< Rng shared data
    ipc_ota_data_t          ota;                ///< OTA data
    position_2d_t           target_position;    ///< Target 2D position
    position_2d_t           current_position;   ///< Current 2D position
    ipc_radio_pdu_t         tx_pdu;             ///< TX PDU
    ipc_radio_pdu_t         rx_pdu;             ///< RX PDU
    ipc_lh2_calibration_t  lh2_calibration;     ///< LH2 calibration data
    ipc_device_info_t       device_info;        ///< What this bot is running
    ipc_crash_report_t      crash_report;       ///< Cause of the most recent reset
} ipc_shared_data_t;

// ipc_shared_data_t is packed, so every member's offset is the running sum of
// the ones before it. The members after `ota` hold 32-bit values that the
// secure core reads and writes with word accesses while SCB->CCR.UNALIGN_TRP
// is set, so a member whose size is not a multiple of 4 shifts them off
// alignment and those accesses take a HardFault instead of faulting loudly at
// the point of the mistake. Assert the alignment here so a size change is
// caught at compile time.
_Static_assert(sizeof(ipc_ota_data_t) % 4 == 0,
               "ipc_ota_data_t size must be a multiple of 4");
_Static_assert(offsetof(ipc_shared_data_t, target_position) % 4 == 0,
               "target_position must be 4-byte aligned");
_Static_assert(offsetof(ipc_shared_data_t, current_position) % 4 == 0,
               "current_position must be 4-byte aligned");
_Static_assert(offsetof(ipc_shared_data_t, lh2_calibration) % 4 == 0,
               "lh2_calibration must be 4-byte aligned");
_Static_assert(sizeof(ipc_device_info_t) % 4 == 0,
               "ipc_device_info_t size must be a multiple of 4");
_Static_assert(offsetof(ipc_shared_data_t, device_info) % 4 == 0,
               "device_info must be 4-byte aligned");
_Static_assert(offsetof(ipc_shared_data_t, crash_report) % 4 == 0,
               "crash_report must be 4-byte aligned");

void mutex_lock(void);

/**
 * @brief Unlock the mutex, has no effect if the mutex is already unlocked
 */
void mutex_unlock(void);

void ipc_network_call(ipc_req_t req);

void release_network_core(void);

#endif
