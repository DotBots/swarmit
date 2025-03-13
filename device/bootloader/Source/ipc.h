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
#include <stdint.h>
#include "protocol.h"

#define IPC_IRQ_PRIORITY (1)

typedef enum {
    IPC_REQ_NONE,        ///< Sorry, but nothing
    IPC_BLINK_INIT_REQ,
    IPC_BLINK_NODE_TX_REQ,
    IPC_RNG_INIT_REQ,                ///< Request for rng init
    IPC_RNG_READ_REQ,                ///< Request for rng read
} ipc_req_t;

typedef enum {
    IPC_CHAN_REQ                = 0,    ///< Channel used for request events
    IPC_CHAN_RADIO_RX           = 1,    ///< Channel used for radio RX events
    IPC_CHAN_APPLICATION_START  = 2,    ///< Channel used for starting the application
    IPC_CHAN_APPLICATION_STOP   = 3,    ///< Channel used for stopping the application
    IPC_CHAN_APPLICATION_RESET  = 4,    ///< Channel used for resetting the application
    IPC_CHAN_LOG_EVENT          = 5,    ///< Channel used for logging events
    IPC_CHAN_OTA_START          = 6,    ///< Channel used for starting an OTA process
    IPC_CHAN_OTA_CHUNK          = 7,    ///< Channel used for writing a non secure image chunk
    IPC_CHAN_LH2_LOCATION       = 8,    ///< Channel used to notify of a new location received
} ipc_channels_t;

typedef struct __attribute__((packed)) {
    uint8_t length;
    uint8_t data[INT8_MAX];
} ipc_log_data_t;

typedef struct __attribute__((packed)) {
    uint32_t image_size;
    uint32_t chunk_count;
    uint32_t chunk_index;
    uint32_t chunk_size;
    uint8_t chunk[INT8_MAX + 1];
    uint8_t hashes_match;
} ipc_ota_data_t;

typedef struct {
    uint8_t value;  ///< Byte containing the random value read
} ipc_rng_data_t;

typedef struct __attribute__((packed)) {
    uint8_t length;             ///< Length of the pdu in bytes
    uint8_t buffer[UINT8_MAX];  ///< Buffer containing the pdu data
} ipc_radio_pdu_t;

typedef struct __attribute__((packed)) {
    bool                    net_ready;          ///< Network core is ready
    bool                    net_ack;            ///< Network core acked the latest request
    ipc_req_t               req;                ///< IPC network request
    uint8_t                 status;             ///< Experiment status
    ipc_log_data_t          log;                ///< Log data
    ipc_rng_data_t          rng;                ///< Rng shared data
    ipc_ota_data_t          ota;                ///< OTA data
    protocol_lh2_location_t current_location;   ///< LH2 current location
    protocol_lh2_location_t target_location;    ///< LH2 target location
    ipc_radio_pdu_t         tx_pdu;             ///< TX PDU
    ipc_radio_pdu_t         rx_pdu;             ///< RX PDU
} ipc_shared_data_t;

void mutex_lock(void);

/**
 * @brief Unlock the mutex, has no effect if the mutex is already unlocked
 */
void mutex_unlock(void);

void ipc_network_call(ipc_req_t req);

void release_network_core(void);

#endif
