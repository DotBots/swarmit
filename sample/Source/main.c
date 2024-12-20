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

#define IPC_CHAN_RADIO_RX   (1U)
#define GPIO_P0_PIN (28)  // LED0 on nRF5340DK

typedef struct {
    uint8_t buffer[UINT8_MAX];
    size_t length;
} rx_data_t;

static rx_data_t _rx_data = { 0 };

void reload_wdt0(void);
void send_data(const uint8_t *packet, uint8_t length);
void rx_data(uint8_t *packet, size_t *length);
void log_data(uint8_t *data, size_t length);
static bool _timer_running = false;

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
        reload_wdt0();
        send_data((uint8_t *)"Hello", 5);
        log_data((uint8_t *)"Logging", 7);
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
    if (NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX]) {
        NRF_IPC_NS->EVENTS_RECEIVE[IPC_CHAN_RADIO_RX] = 0;
        rx_data(_rx_data.buffer, &_rx_data.length);
        printf("Message received (%dB): %s\n", _rx_data.length - 34, &_rx_data.buffer[34]);
        memset(_rx_data.buffer, 0, UINT8_MAX);
    }
}
