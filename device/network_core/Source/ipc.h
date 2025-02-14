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
#include "radio.h"
#include "tdma_client.h"

#define IPC_IRQ_PRIORITY (1)

#define IPC_LOG_SIZE     (128)

typedef enum {
    IPC_REQ_NONE,        ///< Sorry, but nothing
    IPC_TDMA_CLIENT_INIT_REQ,        ///< Request for TDMA client initialization
    IPC_TDMA_CLIENT_SET_TABLE_REQ,   ///< Request for setting the TDMA client timing table
    IPC_TDMA_CLIENT_GET_TABLE_REQ,   ///< Request for reading the TDMA client timing table
    IPC_TDMA_CLIENT_TX_REQ,          ///< Request for a TDMA client TX
    IPC_TDMA_CLIENT_FLUSH_REQ,       ///< Request for flushing the TDMA client message buffer
    IPC_TDMA_CLIENT_EMPTY_REQ,       ///< Request for erasing the TDMA client message buffer
    IPC_TDMA_CLIENT_STATUS_REQ,      ///< Request for reading the TDMA client driver status
    IPC_RNG_INIT_REQ,                ///< Request for rng init
    IPC_RNG_READ_REQ,                ///< Request for rng read
} ipc_req_t;

typedef enum {
    IPC_CHAN_REQ                = 0,    ///< Channel used for request events
    IPC_CHAN_RADIO_RX           = 1,    ///< Channel used for radio RX events
    IPC_CHAN_EXPERIMENT_START   = 2,    ///< Channel used for starting the experiment
    IPC_CHAN_EXPERIMENT_STOP    = 3,    ///< Channel used for stopping the experiment
    IPC_CHAN_LOG_EVENT          = 4,    ///< Channel used for logging events
    IPC_CHAN_OTA_START          = 5,    ///< Channel used for starting an OTA process
    IPC_CHAN_OTA_CHUNK          = 6,    ///< Channel used for writing a non secure image chunk
} ipc_channels_t;

typedef struct {
    uint8_t value;  ///< Byte containing the random value read
} ipc_rng_data_t;

typedef struct __attribute__((packed)) {
    uint8_t length;             ///< Length of the pdu in bytes
    uint8_t buffer[UINT8_MAX];  ///< Buffer containing the pdu data
} ipc_radio_pdu_t;

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

typedef struct __attribute__((packed)) {
    radio_mode_t              mode;                ///< radio_init function parameters
    uint8_t                   frequency;           ///< db_set_frequency function parameters
    tdma_client_table_t       table_set;           ///< db_tdma_client_set_table function parameter
    tdma_client_table_t       table_get;           ///< db_tdma_client_get_table function parameter
    ipc_radio_pdu_t           tx_pdu;              ///< PDU to send
    ipc_radio_pdu_t           rx_pdu;              ///< Received pdu
    tdma_registration_state_t registration_state;  ///< db_tdma_client_get_status return value
} ipc_tdma_client_data_t;

typedef struct __attribute__((packed)) {
    bool                   net_ready;   ///< Network core is ready
    bool                   net_ack;     ///< Network core acked the latest request
    ipc_req_t              req;         ///< IPC network request
    uint8_t                status;      ///< Experiment status
    ipc_log_data_t         log;         ///< Log data
    ipc_rng_data_t         rng;         ///< Rng shared data
    ipc_ota_data_t         ota;         ///< OTA data
    ipc_tdma_client_data_t tdma_client; ///< TDMA client drv shared data
    ipc_radio_pdu_t        data_pdu;    ///< User data pdu
} ipc_shared_data_t;

/**
 * @brief Lock the mutex, blocks until the mutex is locked
 */
static inline void mutex_lock(void) {
    while (NRF_APPMUTEX_NS->MUTEX[0]) {}
}

/**
 * @brief Unlock the mutex, has no effect if the mutex is already unlocked
 */
static inline void mutex_unlock(void) {
    NRF_APPMUTEX_NS->MUTEX[0] = 0;
}

#endif
