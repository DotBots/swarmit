#include <nrf.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "board_config.h"
#include "clock.h"
#include "device.h"
#include "gpio.h"
#include "hdlc.h"
#include "timer.h"
#include "uart.h"

#include "packet.h"
#include "mira.h"

//=========================== defines ==========================================
#define TIMER_DEV           (1)
#define BUFFER_MAX_BYTES (255U)       ///< Max bytes in UART receive buffer
#define UART_BAUDRATE    (1000000UL)  ///< UART baudrate used by the gateway
#define UART_INDEX       (0)  ///< Index of UART peripheral to use
#define RADIO_QUEUE_SIZE (64U)                             ///< Size of the radio queue (must by a power of 2)
#define UART_QUEUE_SIZE  ((BUFFER_MAX_BYTES + 1) * 2)  ///< Size of the UART queue size (must by a power of 2)

typedef struct {
    uint8_t length;                       ///< Length of the radio packet
    uint8_t buffer[BUFFER_MAX_BYTES];  ///< Buffer containing the radio packet
} gateway_radio_packet_t;

typedef struct {
    uint8_t                current;                       ///< Current position in the queue
    uint8_t                last;                          ///< Position of the last item added in the queue
    gateway_radio_packet_t packets[RADIO_QUEUE_SIZE];  ///< Buffer containing the received bytes
} gateway_radio_packet_queue_t;

typedef struct {
    uint16_t current;                     ///< Current position in the queue
    uint16_t last;                        ///< Position of the last item added in the queue
    uint8_t  buffer[UART_QUEUE_SIZE];  ///< Buffer containing the received bytes
} gateway_uart_queue_t;

typedef struct {
    uint8_t                      hdlc_rx_buffer[BUFFER_MAX_BYTES * 2];  ///< Buffer where message received on UART is stored
    uint8_t                      hdlc_tx_buffer[BUFFER_MAX_BYTES * 2];  ///< Internal buffer used for sending serial HDLC frames
    uint32_t                     buttons;                                  ///< Buttons state (one byte per button)
    uint8_t                      radio_tx_buffer[BUFFER_MAX_BYTES];     ///< Internal buffer that contains the command to send (from buttons)
    gateway_radio_packet_queue_t radio_queue;                              ///< Queue used to process received radio packets outside of interrupt
    gateway_uart_queue_t         uart_queue;                               ///< Queue used to process received UART bytes outside of interrupt
    bool                         led1_mira;                               ///< Whether the status LED should mira
    bool                         client_connected;
} gateway_vars_t;

//=========================== variables ========================================

extern schedule_t schedule_minuscule, schedule_tiny, schedule_small, schedule_huge, schedule_only_beacons, schedule_only_beacons_optimized_scan;
static gateway_vars_t _gw_vars;

//=========================== callbacks ========================================

static void _uart_callback(uint8_t data) {
    _gw_vars.uart_queue.buffer[_gw_vars.uart_queue.last] = data;
    _gw_vars.uart_queue.last                             = (_gw_vars.uart_queue.last + 1) & (UART_QUEUE_SIZE - 1);
}

void mira_event_callback(mr_event_t event, mr_event_data_t event_data) {
    switch (event) {
        case MIRA_NEW_PACKET:
        {
            memcpy(_gw_vars.radio_queue.packets[_gw_vars.radio_queue.last].buffer, event_data.data.new_packet.header, sizeof(mr_packet_header_t));
            memcpy(_gw_vars.radio_queue.packets[_gw_vars.radio_queue.last].buffer + sizeof(mr_packet_header_t), event_data.data.new_packet.payload, event_data.data.new_packet.payload_len);
            _gw_vars.radio_queue.packets[_gw_vars.radio_queue.last].length = sizeof(mr_packet_header_t) + event_data.data.new_packet.payload_len;
            _gw_vars.radio_queue.last                                      = (_gw_vars.radio_queue.last + 1) & (RADIO_QUEUE_SIZE - 1);
            break;
        }
        case MIRA_NODE_JOINED:
            printf("New node joined: %016llX\n", event_data.data.node_info.node_id);
            uint64_t joined_nodes[MIRA_MAX_NODES] = { 0 };
            uint8_t joined_nodes_len = mira_gateway_get_nodes(joined_nodes);
            printf("Number of connected nodes: %d\n", joined_nodes_len);
            // TODO: send list of joined_nodes to Edge Gateway via UART
            break;
        case MIRA_NODE_LEFT:
            printf("Node left: %016llX, reason: %u\n", event_data.data.node_info.node_id, event_data.tag);
            printf("Number of connected nodes: %d\n", mira_gateway_count_nodes());
            break;
        case MIRA_ERROR:
            printf("Error\n");
            break;
        default:
            break;
    }
}

static void _led1_mira_fast(void) {
    if (_gw_vars.led1_mira) {
        db_gpio_toggle(&db_led1);
    }
}

static void _led2_shutdown(void) {
    db_gpio_set(&db_led2);
}

static void _led3_shutdown(void) {
    db_gpio_set(&db_led3);
}

//=========================== main =============================================

int main(void) {
    db_hfclk_init();
    _gw_vars.led1_mira = true;
    // Initialize user feedback LEDs
    db_gpio_init(&db_led1, DB_GPIO_OUT);  // Global status
    db_gpio_set(&db_led1);
    db_timer_init(TIMER_DEV);
    db_timer_set_periodic_ms(TIMER_DEV, 0, 50, _led1_mira_fast);
    db_timer_set_periodic_ms(TIMER_DEV, 1, 20, _led2_shutdown);
    db_timer_set_periodic_ms(TIMER_DEV, 2, 20, _led3_shutdown);
    db_gpio_init(&db_led2, DB_GPIO_OUT);  // Packet received from Radio (e.g from a DotBot)
    db_gpio_set(&db_led2);
    db_gpio_init(&db_led3, DB_GPIO_OUT);  // Packet received from UART (e.g from the computer)
    db_gpio_set(&db_led3);

    // Configure Radio as transmitter
    mira_init(MIRA_GATEWAY, &schedule_tiny, &mira_event_callback);

    // Initialize the gateway context
    _gw_vars.buttons             = 0x0000;
    _gw_vars.radio_queue.current = 0;
    _gw_vars.radio_queue.last    = 0;
    db_uart_init(UART_INDEX, &db_uart_rx, &db_uart_tx, UART_BAUDRATE, &_uart_callback);

    // Initialization done, wait a bit and shutdown status LED
    db_timer_delay_s(TIMER_DEV, 1);
    db_gpio_set(&db_led1);
    _gw_vars.led1_mira = false;

    puts("Gateway is ready");

    while (1) {

        while (_gw_vars.radio_queue.current != _gw_vars.radio_queue.last) {
            db_gpio_clear(&db_led2);
            size_t frame_len = db_hdlc_encode(_gw_vars.radio_queue.packets[_gw_vars.radio_queue.current].buffer, _gw_vars.radio_queue.packets[_gw_vars.radio_queue.current].length, _gw_vars.hdlc_tx_buffer);
            printf("Radio packet received (%d B): payload=", _gw_vars.radio_queue.packets[_gw_vars.radio_queue.current].length);
            for (int i = 0; i < _gw_vars.radio_queue.packets[_gw_vars.radio_queue.current].length; i++) {
                printf("%02X ", _gw_vars.radio_queue.packets[_gw_vars.radio_queue.current].buffer[i]);
            }
            printf("\n");
            if (_gw_vars.client_connected) {
                db_uart_write(UART_INDEX, _gw_vars.hdlc_tx_buffer, frame_len);
            }
            _gw_vars.radio_queue.current = (_gw_vars.radio_queue.current + 1) & (RADIO_QUEUE_SIZE - 1);
        }

        while (_gw_vars.uart_queue.current != _gw_vars.uart_queue.last) {
            db_gpio_clear(&db_led3);
            db_hdlc_state_t hdlc_state = db_hdlc_rx_byte(_gw_vars.uart_queue.buffer[_gw_vars.uart_queue.current]);
            switch ((uint8_t)hdlc_state) {
                case DB_HDLC_STATE_IDLE:
                case DB_HDLC_STATE_RECEIVING:
                case DB_HDLC_STATE_ERROR:
                    break;
                case DB_HDLC_STATE_READY:
                {
                    size_t msg_len = db_hdlc_decode(_gw_vars.hdlc_rx_buffer);
                    if (msg_len) {
                        if (!_gw_vars.client_connected && _gw_vars.hdlc_rx_buffer[1] == 0xff) {
                            _gw_vars.client_connected = true;
                            puts("UART client connected");
                            break;
                        }
                        if (_gw_vars.client_connected && _gw_vars.hdlc_rx_buffer[1] == 0xfe) {
                            _gw_vars.client_connected = false;
                            puts("UART client disconnected");
                            break;
                        }
                        mr_packet_header_t *header = (mr_packet_header_t *)_gw_vars.hdlc_rx_buffer;
                        header->dst = MIRA_BROADCAST_ADDRESS;
                        header->src = db_device_id();
                        header->version = MIRA_PROTOCOL_VERSION;
                        header->type = MIRA_PACKET_DATA;
                        memcpy(_gw_vars.hdlc_rx_buffer, header, sizeof(mr_packet_header_t));
                        printf("UART packet received (%d B): payload=", msg_len);
                        for (size_t i = 0; i < msg_len; i++) {
                            printf("%02X ", _gw_vars.hdlc_rx_buffer[i]);
                        }
                        printf("\n");
                        mira_tx(_gw_vars.hdlc_rx_buffer, msg_len);
                    }
                } break;
                default:
                    break;
            }
            _gw_vars.uart_queue.current = (_gw_vars.uart_queue.current + 1) & (UART_QUEUE_SIZE - 1);
        }
    }
}
