/**
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief Sample non secure application
 *
 * @copyright Inria, 2024
 *
 */

#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <nrf.h>

#define GPIO_P0_PIN (28)  // LED0 on nRF5340DK

typedef void (*ipc_isr_cb_t)(const uint8_t *, size_t);
typedef struct __attribute__((packed)) {
    uint8_t type;
    uint8_t length;
    uint8_t content[UINT8_MAX];
} msg_packet_t;

void swarmit_keep_alive(void);
void swarmit_send_data_packet(const uint8_t *packet, uint8_t length);
void swarmit_ipc_isr(ipc_isr_cb_t cb);
void swarmit_log_data(uint8_t *data, size_t length);
static bool _timer_running = false;

static void _rx_data_callback(const uint8_t *data, size_t length) {
    (void)length;
    msg_packet_t *msg = (msg_packet_t *)(data);
    msg->content[msg->length] = 0;
    printf("Message (type: %02X) received (%dB): %s\n", msg->type, msg->length, (char *)msg->content);
}

static void delay_ms(uint32_t ms) {
    NRF_TIMER0_NS->TASKS_CAPTURE[0] = 1;
    NRF_TIMER0_NS->CC[0] += ms * 1000;
    _timer_running = true;
    while (_timer_running) {
        __WFE();
    }
}

int main(void) {
    puts("Hello Non Secure World!");
    NRF_P0_NS->DIRSET = (1 << GPIO_P0_PIN);

    NRF_TIMER0_NS->TASKS_CLEAR = 1;
    NRF_TIMER0_NS->PRESCALER   = 4;  // Run TIMER at 1MHz
    NRF_TIMER0_NS->BITMODE     = (TIMER_BITMODE_BITMODE_32Bit << TIMER_BITMODE_BITMODE_Pos);
    NRF_TIMER0_NS->INTEN       = (TIMER_INTENSET_COMPARE0_Enabled << TIMER_INTENSET_COMPARE0_Pos);
    NVIC_EnableIRQ(TIMER0_IRQn);
    NRF_TIMER0_NS->TASKS_START = 1;

    while (1) {
        delay_ms(500);
        swarmit_keep_alive();
        swarmit_send_data_packet((uint8_t *)"Hello", 5);
        swarmit_log_data((uint8_t *)"Logging", 7);
        // Crash on purpose
        //uint32_t *addr = 0x0;
        //*addr = 0xdead;
        NRF_P0_NS->OUT ^= (1 << GPIO_P0_PIN);
    };
}

void TIMER0_IRQHandler(void) {

    if (NRF_TIMER0_NS->EVENTS_COMPARE[0] == 1) {
        NRF_TIMER0_NS->EVENTS_COMPARE[0] = 0;
        _timer_running = false;
    }
}

void IPC_IRQHandler(void) {
    swarmit_ipc_isr(_rx_data_callback);
}
