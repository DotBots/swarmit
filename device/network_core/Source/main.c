/**
 * @file
 * @defgroup project_nrf5340_net_core   nRF5340 network core
 * @ingroup projects
 * @brief This application is used to control the radio and rng peripherals and to interact with the application core
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @copyright Inria, 2023
 */

#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <nrf.h>
// Include BSP headers
#include "ipc.h"
#include "protocol.h"
#include "rng.h"
#include "sha256.h"

// Blink includes
#include "bl_timer_hf.h"
#include "blink.h"
#include "models.h"

#define NETCORE_MAIN_TIMER                  (0)

//=========================== variables =========================================

typedef struct {
    bool        req_received;
    bool        data_received;
#if defined(USE_LH2)
    bool        lh2_location_received;
#endif
    uint8_t     req_buffer[255];
    uint8_t     notification_buffer[255];
    ipc_req_t   ipc_req;
    bool        ipc_log_received;
    uint8_t     gpio_event_idx;
    uint8_t     expected_hash[SWRMT_OTA_SHA256_LENGTH];
    uint8_t     computed_hash[SWRMT_OTA_SHA256_LENGTH];
    uint64_t    device_id;
} swrmt_app_data_t;

static swrmt_app_data_t _app_vars = { 0 };
extern schedule_t schedule_minuscule, schedule_tiny, schedule_small, schedule_huge, schedule_only_beacons, schedule_only_beacons_optimized_scan;

volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

//=========================== functions =========================================

static void _handle_packet(uint8_t *packet, uint8_t length) {
    memcpy(_app_vars.req_buffer, packet + sizeof(protocol_header_t), length - sizeof(protocol_header_t));
    uint8_t *ptr = _app_vars.req_buffer;
    uint8_t packet_type = (uint8_t)*ptr++;
    if ((packet_type >= SWRMT_REQUEST_STATUS) && (packet_type <= SWRMT_REQUEST_OTA_CHUNK)) {
        uint64_t target_device_id;
        memcpy(&target_device_id, ptr, sizeof(uint64_t));
        if (target_device_id != _app_vars.device_id && target_device_id != 0) {
            // Ignore packet not targetting this device
            return;
        }

        _app_vars.req_received = true;
        return;
    }

#if defined(USE_LH2)
    // Handle LH2 position packets only if in resetting status
    if ((packet_type == PROTOCOL_LH2_LOCATION) && (ipc_shared_data.status == SWRMT_APPLICATION_RESETTING)) {
        memcpy((uint8_t *)&ipc_shared_data.current_location, ptr, sizeof(protocol_lh2_location_t));
        _app_vars.lh2_location_received = true;
        return;
    }
#endif

    // ignore other types of packet if not in running mode
    if (ipc_shared_data.status != SWRMT_APPLICATION_RUNNING) {
        return;
    }

    ipc_shared_data.rx_pdu.length = length - 2;
    memcpy((uint8_t *)ipc_shared_data.rx_pdu.buffer, packet, length - 2);
    _app_vars.data_received = true;
}

static void blink_event_callback(bl_event_t event, bl_event_data_t event_data) {
    switch (event) {
        case BLINK_NEW_PACKET:
            _handle_packet(event_data.data.new_packet.packet, event_data.data.new_packet.length);
            break;
        case BLINK_CONNECTED: {
            uint64_t gateway_id = event_data.data.gateway_info.gateway_id;
            printf("Connected to gateway %016llX\n", gateway_id);
            break;
        }
        case BLINK_DISCONNECTED: {
            uint64_t gateway_id = event_data.data.gateway_info.gateway_id;
            printf("Disconnected from gateway %016llX, reason: %u\n", gateway_id, event_data.tag);
            break;
        }
        case BLINK_ERROR:
            printf("Error\n");
            break;
        default:
            break;
    }
}

uint64_t _deviceid(void) {
    return ((uint64_t)NRF_FICR_NS->INFO.DEVICEID[1]) << 32 | (uint64_t)NRF_FICR_NS->INFO.DEVICEID[0];
}

//=========================== main ==============================================

int main(void) {

    _app_vars.device_id = _deviceid();

    NRF_IPC_NS->INTENSET                             = (1 << IPC_CHAN_REQ) | (1 << IPC_CHAN_LOG_EVENT);
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_RADIO_RX]          = 1 << IPC_CHAN_RADIO_RX;
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_APPLICATION_START] = 1 << IPC_CHAN_APPLICATION_START;
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_APPLICATION_STOP]  = 1 << IPC_CHAN_APPLICATION_STOP;
    //NRF_IPC_NS->SEND_CNF[IPC_CHAN_APPLICATION_RESET] = 1 << IPC_CHAN_APPLICATION_RESET;
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_OTA_START]         = 1 << IPC_CHAN_OTA_START;
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_OTA_CHUNK]         = 1 << IPC_CHAN_OTA_CHUNK;
    NRF_IPC_NS->SEND_CNF[IPC_CHAN_LH2_LOCATION]      = 1 << IPC_CHAN_LH2_LOCATION;
    NRF_IPC_NS->RECEIVE_CNF[IPC_CHAN_REQ]            = 1 << IPC_CHAN_REQ;
    NRF_IPC_NS->RECEIVE_CNF[IPC_CHAN_LOG_EVENT]      = 1 << IPC_CHAN_LOG_EVENT;

    NVIC_EnableIRQ(IPC_IRQn);
    NVIC_ClearPendingIRQ(IPC_IRQn);
    NVIC_SetPriority(IPC_IRQn, 1);

    // Configure timer used for timestamping events
    bl_timer_hf_init(NETCORE_MAIN_TIMER);

    // Network core must remain on
    ipc_shared_data.net_ready = true;

    while (1) {
        __WFE();

        if (_app_vars.req_received) {
            _app_vars.req_received = false;
            swrmt_request_t *req = (swrmt_request_t *)_app_vars.req_buffer;
            switch (req->type) {
                case SWRMT_REQUEST_STATUS:
                {
                    size_t length = 0;
                    _app_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_STATUS;
                    uint64_t device_id = _deviceid();
                    memcpy(_app_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
                    length += sizeof(uint64_t);
                    _app_vars.notification_buffer[length++] = ipc_shared_data.status;
                    blink_node_tx(_app_vars.notification_buffer, length);
                }   break;
                case SWRMT_REQUEST_START:
                    if (ipc_shared_data.status != SWRMT_APPLICATION_READY) {
                        break;
                    }
                    NRF_IPC_NS->TASKS_SEND[IPC_CHAN_APPLICATION_START] = 1;
                    break;
                case SWRMT_REQUEST_STOP:
                    if ((ipc_shared_data.status != SWRMT_APPLICATION_RUNNING) && (ipc_shared_data.status != SWRMT_APPLICATION_RESETTING)) {
                        break;
                    }
                    ipc_shared_data.status = SWRMT_APPLICATION_STOPPING;
                    NRF_IPC_NS->TASKS_SEND[IPC_CHAN_APPLICATION_STOP] = 1;
                    break;
                case SWRMT_REQUEST_RESET:
                    if (ipc_shared_data.status != SWRMT_APPLICATION_READY) {
                        break;
                    }
#if defined(USE_LH2)
                    memcpy((uint8_t *)&ipc_shared_data.target_location, req->data, sizeof(protocol_lh2_location_t));
#endif
                    ipc_shared_data.status = SWRMT_APPLICATION_RESETTING;
                    //NRF_IPC_NS->TASKS_SEND[IPC_CHAN_APPLICATION_RESET] = 1;
                    break;
                case SWRMT_REQUEST_OTA_START:
                {
                    if (ipc_shared_data.status != SWRMT_APPLICATION_READY) {
                        break;
                    }
                    const swrmt_ota_start_pkt_t *pkt = (const swrmt_ota_start_pkt_t *)req->data;
                    // Copy expected hash
                    memcpy(_app_vars.expected_hash, pkt->hash, SWRMT_OTA_SHA256_LENGTH);

                    // Initialize computed hash
                    memset(_app_vars.computed_hash, 0, SWRMT_OTA_SHA256_LENGTH);
                    crypto_sha256_init();

                    // Erase the corresponding flash pages.
                    mutex_lock();
                    ipc_shared_data.ota.image_size = pkt->image_size;
                    ipc_shared_data.ota.chunk_count = pkt->chunk_count;
                    ipc_shared_data.ota.hashes_match = 0;
                    mutex_unlock();
                    NRF_IPC_NS->TASKS_SEND[IPC_CHAN_OTA_START] = 1;
                } break;
                case SWRMT_REQUEST_OTA_CHUNK:
                {
                    if (ipc_shared_data.status != SWRMT_APPLICATION_READY) {
                        break;
                    }
                    const swrmt_ota_chunk_pkt_t *pkt = (const swrmt_ota_chunk_pkt_t *)req->data;
                    mutex_lock();
                    ipc_shared_data.ota.chunk_index = pkt->index;
                    ipc_shared_data.ota.chunk_size = pkt->chunk_size;
                    memcpy((uint8_t *)ipc_shared_data.ota.chunk, pkt->chunk, pkt->chunk_size);
                    mutex_unlock();

                    // Update computed hash
                    crypto_sha256_update((const uint8_t *)ipc_shared_data.ota.chunk, ipc_shared_data.ota.chunk_size);

                    // If last chunk, finalize computed hash, compare with expected hash and report to application core via shared memory
                    if (ipc_shared_data.ota.chunk_index == ipc_shared_data.ota.chunk_count - 1) {
                        crypto_sha256(_app_vars.computed_hash);
                        mutex_lock();
                        ipc_shared_data.ota.hashes_match = !memcmp(_app_vars.computed_hash, _app_vars.expected_hash, SWRMT_OTA_SHA256_LENGTH);
                        mutex_unlock();
                    }

                    NRF_IPC_NS->TASKS_SEND[IPC_CHAN_OTA_CHUNK] = 1;
                } break;
                default:
                    break;
            }
        }

#if defined(USE_LH2)
        if (_app_vars.lh2_location_received) {
            NRF_IPC_NS->TASKS_SEND[IPC_CHAN_LH2_LOCATION] = 1;
        }
#endif

        if (_app_vars.ipc_req != IPC_REQ_NONE) {
            ipc_shared_data.net_ack = false;
            switch (_app_vars.ipc_req) {
                // Blink node functions
                case IPC_BLINK_INIT_REQ:
                    blink_init(BLINK_NODE, &schedule_minuscule, &blink_event_callback);
                    break;
                case IPC_BLINK_NODE_TX_REQ:
                    blink_node_tx((uint8_t *)ipc_shared_data.tx_pdu.buffer, ipc_shared_data.tx_pdu.length);
                    break;
                case IPC_RNG_INIT_REQ:
                    db_rng_init();
                    break;
                case IPC_RNG_READ_REQ:
                    db_rng_read((uint8_t *)&ipc_shared_data.rng.value);
                    break;
                default:
                    break;
            }
            ipc_shared_data.net_ack = true;
            _app_vars.ipc_req      = IPC_REQ_NONE;
        }

        if (_app_vars.data_received) {
            _app_vars.data_received = false;
            NRF_IPC_NS->TASKS_SEND[IPC_CHAN_RADIO_RX] = 1;
        }

        if (_app_vars.ipc_log_received) {
            _app_vars.ipc_log_received = false;
            // Notify log data
            size_t length = 0;
            _app_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_LOG_EVENT;
            uint64_t device_id = _deviceid();
            memcpy(_app_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
            length += sizeof(uint64_t);
            uint32_t timestamp = bl_timer_hf_now(NETCORE_MAIN_TIMER);
            memcpy(_app_vars.notification_buffer + length, &timestamp, sizeof(uint32_t));
            length += sizeof(uint32_t);
            memcpy(_app_vars.notification_buffer + length, (void *)&ipc_shared_data.log, ipc_shared_data.log.length + 1);
            length += ipc_shared_data.log.length + 1;
            blink_node_tx(_app_vars.notification_buffer, length);
        }
    };
}

void IPC_IRQHandler(void) {
    if (NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_REQ]) {
        NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_REQ] = 0;
        _app_vars.ipc_req                        = ipc_shared_data.req;
    }

    if (NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_LOG_EVENT]) {
        NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_LOG_EVENT] = 0;
        _app_vars.ipc_log_received                     = true;
    }
}
