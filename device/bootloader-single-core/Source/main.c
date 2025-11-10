/**
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief Device bootloader application
 *
 * @copyright Inria, 2025
 *
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <nrf.h>

#include "battery.h"
#include "nvmc.h"
#include "protocol.h"
#include "mari.h"

// DotBot-firmware includes
#include "board_config.h"
#include "device.h"
#include "gpio.h"
#include "sha256.h"
#include "timer.h"

// Mira includes
#include "mr_timer_hf.h"
#include "mr_radio.h"
#include "models.h"
#include "mac.h"
#include "mari.h"


#define SWARMIT_BASE_ADDRESS        (0x10000)
#define SWRMT_OTA_SHA256_LENGTH     (32U)

#define BATTERY_UPDATE_DELAY        (1000U)
#define POSITION_UPDATE_DELAY_MS    (500U) ///< 100ms delay between each position update

#define NETCORE_MAIN_TIMER          (0)

// Important: select a Network ID according to the specific deployment you are making,
// see the registry at https://crystalfree.atlassian.net/wiki/spaces/Mari/pages/3324903426/Registry+of+Mari+Network+IDs
#define SWARMIT_MARI_NET_ID         (0x12AA)

typedef struct {
    uint8_t         notification_buffer[255];
    uint32_t        base_addr;
    bool            ota_start_request;
    bool            ota_require_erase;
    bool            ota_chunk_request;
    bool            start_application;
    bool            battery_update;
    bool            req_received;
    bool            log_received;
    bool            send_status;
    uint8_t         req_buffer[255];
    crypto_sha256_ctx_t sha256_ctx;
    uint8_t         expected_hash[SWRMT_OTA_SHA256_LENGTH];
    uint8_t         computed_hash[SWRMT_OTA_SHA256_LENGTH];
    uint64_t        device_id;
    int32_t         last_chunk_acked;
    uint32_t        metrics_rx_counter;
    uint32_t        metrics_tx_counter;
    bool            metrics_received;
} bootloader_app_data_t;

/// DotBot protocol LH2 computed location
typedef struct __attribute__((packed)) {
    uint32_t x;  ///< X coordinate, multiplied by 1e6
    uint32_t y;  ///< Y coordinate, multiplied by 1e6
} position_2d_t;

typedef struct __attribute__((packed)) {
    uint8_t length;             ///< Length of the pdu in bytes
    uint8_t buffer[UINT8_MAX];  ///< Buffer containing the pdu data
} radio_pdu_t;

typedef struct __attribute__((packed)) {
    uint8_t length;
    uint8_t data[INT8_MAX];
} log_data_t;

typedef struct __attribute__((packed)) {
    uint32_t image_size;
    uint32_t chunk_count;
    uint32_t chunk_index;
    uint32_t chunk_size;
    int32_t  last_chunk_acked;
    uint8_t chunk[INT8_MAX + 1];
} ota_data_t;

typedef struct {
    uint8_t                 status;             ///< Experiment status
    uint16_t                battery_level;      ///< Battery level in mV
    swrmt_device_type_t     device_type;        ///< Device type
    log_data_t              log;                ///< Log data
    ota_data_t              ota;                ///< OTA data
    radio_pdu_t             tx_pdu;             ///< TX PDU
    radio_pdu_t             rx_pdu;             ///< RX PDU
} swarmit_data_t;

static const gpio_t _status_led = { .port = 1, .pin = 5 };  // TODO: use board specific values

static bootloader_app_data_t _bootloader_vars = { 0 };
static swarmit_data_t _swarmit_vars = { 0 };
extern schedule_t schedule_minuscule, schedule_tiny, schedule_small, schedule_huge, schedule_only_beacons, schedule_only_beacons_optimized_scan;

typedef void (*reset_handler_t)(void);

typedef struct {
    uint32_t msp;                  ///< Main stack pointer
    reset_handler_t reset_handler; ///< Reset handler
} vector_table_t;

static vector_table_t *table = (vector_table_t *)SWARMIT_BASE_ADDRESS; // Image should start with vector table

static void setup_watchdog(void) {

    // Configuration: keep running while sleeping + pause when halted by debugger
    NRF_WDT->CONFIG = (WDT_CONFIG_SLEEP_Run << WDT_CONFIG_SLEEP_Pos |
                         WDT_CONFIG_HALT_Pause << WDT_CONFIG_HALT_Pos);

    // Enable reload register 0
    NRF_WDT->RREN = WDT_RREN_RR0_Enabled << WDT_RREN_RR0_Pos;

    // Configure timeout and callback
    NRF_WDT->CRV = 32768 - 1;
    NRF_WDT->TASKS_START = WDT_TASKS_START_TASKS_START_Trigger << WDT_TASKS_START_TASKS_START_Pos;
}

static void _read_battery(void) {
    _bootloader_vars.battery_update = true;
}

static void _send_status(void) {
    _bootloader_vars.send_status = true;
}

static void _handle_packet(uint64_t dst_address, uint8_t *packet, uint8_t length) {
    memcpy(_bootloader_vars.req_buffer, packet, length);
    uint8_t *ptr = _bootloader_vars.req_buffer;
    uint8_t packet_type = (uint8_t)*ptr++;
    if ((packet_type >= SWRMT_MSG_STATUS) && (packet_type <= SWRMT_MSG_OTA_CHUNK)) {
        _bootloader_vars.req_received = true;
        return;
    }

    if (length == sizeof(mr_metrics_payload_t) && packet_type == MARI_PAYLOAD_TYPE_METRICS_PROBE) {
        _bootloader_vars.metrics_received = true;
        return;
    }

    // ignore other types of packet if not in running mode
    if (_swarmit_vars.status != SWRMT_APPLICATION_RUNNING) {
        return;
    }

    if (dst_address != MARI_BROADCAST_ADDRESS && dst_address != _bootloader_vars.device_id) {
        return;
    }
}

static void mari_event_callback(mr_event_t event, mr_event_data_t event_data) {
    switch (event) {
        case MARI_NEW_PACKET:
        {
            _handle_packet(event_data.data.new_packet.header->dst, event_data.data.new_packet.payload, event_data.data.new_packet.payload_len);
            break;
        }
        case MARI_CONNECTED: {
            uint64_t gateway_id = event_data.data.gateway_info.gateway_id;
            printf("Connected to gateway %016llX\n", gateway_id);
            break;
        }
        case MARI_DISCONNECTED: {
            uint64_t gateway_id = event_data.data.gateway_info.gateway_id;
            printf("Disconnected from gateway %016llX, reason: %u\n", gateway_id, event_data.tag);
            break;
        }
        case MARI_ERROR:
            printf("Error\n");
            break;
        default:
            break;
    }
}

int main(void) {
    _bootloader_vars.device_id = db_device_id();

    // Write device type value to shared memory
#if defined(BOARD_NRF52840DK)
    _swarmit_vars.device_type = SWRMT_DEVICE_TYPE_NRF52840DK;
#else
    _swarmit_vars.device_type = SWRMT_DEVICE_TYPE_UNKNOWN;
#endif

    mari_init(MARI_NODE, SWARMIT_MARI_NET_ID, &schedule_huge, &mari_event_callback);

    battery_level_init();
    _swarmit_vars.battery_level = battery_level_read();

    // Check reset reason and switch to user image if reset was not triggered by any wdt timeout
    uint32_t resetreas = NRF_POWER->RESETREAS;
    NRF_POWER->RESETREAS = NRF_POWER->RESETREAS;

     //Boot user image after soft system reset
    if (resetreas & POWER_RESETREAS_SREQ_Detected << POWER_RESETREAS_SREQ_Pos) {
        // Experiment is running
        _swarmit_vars.status = SWRMT_APPLICATION_RUNNING;

        // Initialize watchdog and non secure access
        setup_watchdog();

        // Set the vector table address prior to jumping to image
        SCB->VTOR = (uint32_t)table;
        __set_MSP(table->msp);
        __set_CONTROL(0);

        // Flush and refill pipeline
        __ISB();

        // Jump to non secure image
        reset_handler_t reset_handler_user_image = table->reset_handler;
        reset_handler_user_image();

        while (1) {}
    }

    _bootloader_vars.base_addr = SWARMIT_BASE_ADDRESS;
    _bootloader_vars.ota_require_erase = true;

    // Status LED
    db_gpio_init(&_status_led, DB_GPIO_OUT);
    // Periodic Timer and Lighthouse initialization
    db_timer_init(1);
    db_timer_set_periodic_ms(1, 1, BATTERY_UPDATE_DELAY, &_read_battery);

    // Configure timer used for timestamping events
    mr_timer_hf_init(NETCORE_MAIN_TIMER);
    mr_timer_hf_set_periodic_us(NETCORE_MAIN_TIMER, 0, 1000000UL, _send_status);

    // Experiment is ready
    _swarmit_vars.status = SWRMT_APPLICATION_READY;

    while (1) {
        __WFE();

        if (_bootloader_vars.send_status) {
            _bootloader_vars.send_status = false;
            size_t length = 0;
            _bootloader_vars.notification_buffer[length++] = SWRMT_MSG_STATUS;
            _bootloader_vars.notification_buffer[length++] = _swarmit_vars.device_type;
            _bootloader_vars.notification_buffer[length++] = _swarmit_vars.status;
            memcpy(&_bootloader_vars.notification_buffer[length], (void *)&_swarmit_vars.battery_level, sizeof(uint16_t));
            length += sizeof(uint16_t);
            position_2d_t position = { 0 };
            memcpy(&_bootloader_vars.notification_buffer[length], (void *)&position, sizeof(position_2d_t));
            length += sizeof(position_2d_t);
            mari_node_tx_payload(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.req_received) {
            _bootloader_vars.req_received = false;
            swrmt_request_t *req = (swrmt_request_t *)_bootloader_vars.req_buffer;
            switch (req->type) {
                case SWRMT_MSG_START:
                    if (_swarmit_vars.status != SWRMT_APPLICATION_READY) {
                        break;
                    }
                    puts("Start request received");
                    NVIC_SystemReset();
                    break;
                case SWRMT_MSG_STOP:
                    if (_swarmit_vars.status != SWRMT_APPLICATION_RUNNING && _swarmit_vars.status != SWRMT_APPLICATION_PROGRAMMING) {
                        break;
                    }
                    puts("Stop request received");
                    setup_watchdog();
                    break;
                case SWRMT_MSG_OTA_START:
                {
                    if (_swarmit_vars.status != SWRMT_APPLICATION_READY && _swarmit_vars.status != SWRMT_APPLICATION_PROGRAMMING) {
                        break;
                    }
                    _swarmit_vars.ota.last_chunk_acked = -1;
                    _swarmit_vars.status = SWRMT_APPLICATION_PROGRAMMING;
                    const swrmt_ota_start_pkt_t *pkt = (const swrmt_ota_start_pkt_t *)req->data;
                    // Erase the corresponding flash pages.
                    _swarmit_vars.ota.image_size = pkt->image_size;
                    _swarmit_vars.ota.chunk_count = pkt->chunk_count;
                    printf("OTA Start request received (size: %u, chunks: %u)\n", _swarmit_vars.ota.image_size, _swarmit_vars.ota.chunk_count);
                    _bootloader_vars.ota_start_request = true;
                } break;
                case SWRMT_MSG_OTA_CHUNK:
                {
                    if (_swarmit_vars.status != SWRMT_APPLICATION_PROGRAMMING && _swarmit_vars.status != SWRMT_APPLICATION_READY) {
                        break;
                    }

                    const swrmt_ota_chunk_pkt_t *pkt = (const swrmt_ota_chunk_pkt_t *)req->data;
                    _swarmit_vars.ota.chunk_index = pkt->index;

                    // Check chunk index is valid
                    if (_swarmit_vars.ota.chunk_index >= _swarmit_vars.ota.chunk_count) {
                        printf("Invalid chunk index %u\n", _swarmit_vars.ota.chunk_index);
                        break;
                    }

                    // Only check for matching sha if chunk was not already acked
                    if (_swarmit_vars.ota.last_chunk_acked != (int32_t)_swarmit_vars.ota.chunk_index) {
                        printf("Verify SHA for chunk %u: ", _swarmit_vars.ota.chunk_index);
                        _swarmit_vars.ota.chunk_size = pkt->chunk_size;
                        memcpy((uint8_t *)_swarmit_vars.ota.chunk, pkt->chunk, pkt->chunk_size);

                        // Copy expected hash
                        memcpy(_bootloader_vars.expected_hash, pkt->sha, SWRMT_OTA_SHA256_LENGTH);

                        // Compute and compare the chunk hash with the received one
                        crypto_sha256_init(&_bootloader_vars.sha256_ctx);
                        crypto_sha256_update(&_bootloader_vars.sha256_ctx, (const uint8_t *)_swarmit_vars.ota.chunk, _swarmit_vars.ota.chunk_size);
                        crypto_sha256(&_bootloader_vars.sha256_ctx, _bootloader_vars.computed_hash);

                        if (memcmp(_bootloader_vars.computed_hash, _bootloader_vars.expected_hash, 8) != 0) {
                            puts("Failed");
                            break;
                        }
                        puts("OK");
                    }
                    printf("Process OTA chunk request (index: %u, size: %u)\n", _swarmit_vars.ota.chunk_index, _swarmit_vars.ota.chunk_size);
                    _bootloader_vars.ota_chunk_request = true;
                } break;
                default:
                    break;
            }
        }

        if (_bootloader_vars.metrics_received) {
            _bootloader_vars.metrics_received = false;
            mr_metrics_payload_t *metrics_payload = (mr_metrics_payload_t *)_bootloader_vars.req_buffer;
            // update metrics probe
            metrics_payload->node_rx_count        = ++_bootloader_vars.metrics_rx_counter;
            metrics_payload->node_rx_asn          = mr_mac_get_asn();
            metrics_payload->node_tx_count        = ++_bootloader_vars.metrics_tx_counter;
            metrics_payload->node_tx_enqueued_asn = mr_mac_get_asn();
            metrics_payload->rssi_at_node         = mr_radio_rssi();

            // send metrics probe to gateway
            mari_node_tx_payload((uint8_t *)metrics_payload, sizeof(mr_metrics_payload_t));
        }

        if (_bootloader_vars.log_received) {
            _bootloader_vars.log_received = false;
            // Notify log data
            size_t length = 0;
            _bootloader_vars.notification_buffer[length++] = SWRMT_MSG_LOG_EVENT;
            uint32_t timestamp = mr_timer_hf_now(NETCORE_MAIN_TIMER);
            memcpy(_bootloader_vars.notification_buffer + length, &timestamp, sizeof(uint32_t));
            length += sizeof(uint32_t);
            memcpy(_bootloader_vars.notification_buffer + length, (void *)&_swarmit_vars.log, _swarmit_vars.log.length + 1);
            length += _swarmit_vars.log.length + 1;
            mari_node_tx_payload(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.ota_start_request) {
            _bootloader_vars.ota_start_request = false;

            if (_bootloader_vars.ota_require_erase) {
                // Erase non secure flash
                uint32_t pages_count = (_swarmit_vars.ota.image_size / FLASH_PAGE_SIZE) + (_swarmit_vars.ota.image_size % FLASH_PAGE_SIZE != 0);
                printf("Pages to erase: %u\n", pages_count);
                for (uint32_t page = 0; page < pages_count; page++) {
                    uint32_t addr = _bootloader_vars.base_addr + page * FLASH_PAGE_SIZE;
                    printf("Erasing page %u at %p\n", page + 16, (uint32_t *)addr);
                    nvmc_page_erase(page + 16);
                }
                printf("Erasing done\n");
                _bootloader_vars.ota_require_erase = false;
            }

            // Notify erase is done
            size_t length = 0;
            _bootloader_vars.notification_buffer[length++] = SWRMT_MSG_OTA_START_ACK;
            while (!mari_node_is_connected()) {}
            mari_node_tx_payload(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.ota_chunk_request) {
            _bootloader_vars.ota_chunk_request = false;

            if (_swarmit_vars.ota.last_chunk_acked != (int32_t)_swarmit_vars.ota.chunk_index) {
                // Write chunk to flash
                uint32_t addr = _bootloader_vars.base_addr + _swarmit_vars.ota.chunk_index * SWRMT_OTA_CHUNK_SIZE;
                printf("Writing chunk %d/%d at address %p\n", _swarmit_vars.ota.chunk_index, _swarmit_vars.ota.chunk_count - 1, (uint32_t *)addr);
                nvmc_write((uint32_t *)addr, (void *)_swarmit_vars.ota.chunk, _swarmit_vars.ota.chunk_size);
                _bootloader_vars.ota_require_erase = true;
            }

            // Notify chunk has been written
            size_t length = 0;
            _bootloader_vars.notification_buffer[length++] = SWRMT_MSG_OTA_CHUNK_ACK;
            memcpy(_bootloader_vars.notification_buffer + length, (void *)&_swarmit_vars.ota.chunk_index, sizeof(uint32_t));
            length += sizeof(uint32_t);
            _swarmit_vars.ota.last_chunk_acked = _swarmit_vars.ota.chunk_index;
            while (!mari_node_is_connected()) {}
            mari_node_tx_payload(_bootloader_vars.notification_buffer, length);

            // If last chunk, finalize computed hash, set back to ready state
            if (_swarmit_vars.ota.chunk_index == _swarmit_vars.ota.chunk_count - 1) {
                _swarmit_vars.status = SWRMT_APPLICATION_READY;
            }
        }

        if (_bootloader_vars.battery_update) {
            db_gpio_toggle(&_status_led);
            _swarmit_vars.battery_level = battery_level_read();
            _bootloader_vars.battery_update = false;
        }
    }
}
