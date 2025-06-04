/**
 * @file
 * @ingroup bsp_uart_block
 *
 * @brief  nRF52833-specific definition of the "uart block mode" bsp module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2025
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <nrf.h>
#include <nrf_peripherals.h>

#include "board_config.h"
#include "gpio.h"
#include "uart.h"

//=========================== defines ==========================================

#define NRF_UART_TIMER  (NRF_TIMER4)
#define TIMER_CC_NUM    TIMER4_CC_NUM
#define TIMER_IRQ       TIMER4_IRQn

#define DB_UARTE_CHUNK_SIZE  (64U)
#define DB_UARTE_BUFFER_SIZE (UINT8_MAX)  ///< Maximum size of the buffer to store received data, 256 bytes

typedef enum {
    IDLE,
    FRAME_RX,
} uart_state_t;

typedef struct {
    NRF_UARTE_Type *p;
    IRQn_Type       irq;
} uart_conf_t;

typedef struct {
    uart_rx_cb_t callback;  ///< pointer to the callback function
    uart_state_t state;
    uint8_t      buffer[DB_UARTE_BUFFER_SIZE];  ///< buffer to store the received data
} uart_vars_t;

//=========================== variables ========================================

static const uart_conf_t _devs[UARTE_COUNT] = {
    {
        .p   = NRF_UARTE0,
        .irq = UARTE0_UART0_IRQn,
    },
    {
        .p   = NRF_UARTE1,
        .irq = UARTE1_IRQn,
    },
};

static uart_vars_t _uart_vars[UARTE_COUNT] = { 0 };  ///< variable handling the UART context

//=========================== public ===========================================

void swarmit_uart_init(uart_t uart, const gpio_t *rx_pin, const gpio_t *tx_pin, uint32_t baudrate, uart_rx_cb_t callback) {

    // configure UART pins (RX as input, TX as output);
    db_gpio_init(rx_pin, DB_GPIO_IN_PU);
    db_gpio_init(tx_pin, DB_GPIO_OUT);

    // configure UART
    _devs[uart].p->CONFIG   = 0;
    _devs[uart].p->PSEL.RXD = (rx_pin->port << UARTE_PSEL_RXD_PORT_Pos) |
                              (rx_pin->pin << UARTE_PSEL_RXD_PIN_Pos) |
                              (UARTE_PSEL_RXD_CONNECT_Connected << UARTE_PSEL_RXD_CONNECT_Pos);
    _devs[uart].p->PSEL.TXD = (tx_pin->port << UARTE_PSEL_TXD_PORT_Pos) |
                              (tx_pin->pin << UARTE_PSEL_TXD_PIN_Pos) |
                              (UARTE_PSEL_TXD_CONNECT_Connected << UARTE_PSEL_TXD_CONNECT_Pos);
    _devs[uart].p->PSEL.RTS = 0xffffffff;  // pin disconnected
    _devs[uart].p->PSEL.CTS = 0xffffffff;  // pin disconnected

    // configure baudrate
    switch (baudrate) {
        case 1200:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud1200 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 9600:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud9600 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 14400:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud14400 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 19200:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud19200 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 28800:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud28800 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 31250:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud31250 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 38400:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud38400 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 56000:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud56000 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 57600:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud57600 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 76800:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud76800 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 115200:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud115200 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 230400:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud230400 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 250000:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud250000 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 460800:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud460800 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 921600:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud921600 << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        case 1000000:
            _devs[uart].p->BAUDRATE = (UARTE_BAUDRATE_BAUDRATE_Baud1M << UARTE_BAUDRATE_BAUDRATE_Pos);
            break;
        default:
            // error, return without enabling UART
            return;
    }

    _devs[uart].p->ENABLE = (UARTE_ENABLE_ENABLE_Enabled << UARTE_ENABLE_ENABLE_Pos);

    if (callback) {
        _uart_vars[uart].callback    = callback;
        _devs[uart].p->RXD.MAXCNT    = 1;
        _devs[uart].p->RXD.PTR       = (uint32_t)_uart_vars[uart].buffer;
        _devs[uart].p->INTENSET      = (UARTE_INTENSET_ENDRX_Enabled << UARTE_INTENSET_ENDRX_Pos);
        _devs[uart].p->TASKS_STARTRX = 1;
        NVIC_EnableIRQ(_devs[uart].irq);
        NVIC_SetPriority(_devs[uart].irq, 0);
        NVIC_ClearPendingIRQ(_devs[uart].irq);
    }

    // Configure the timer
    NRF_UART_TIMER->TASKS_CLEAR = 1;
    NRF_UART_TIMER->PRESCALER   = 4;  // Run TIMER at 1MHz
    NRF_UART_TIMER->BITMODE     = (TIMER_BITMODE_BITMODE_32Bit << TIMER_BITMODE_BITMODE_Pos);
    NRF_UART_TIMER->INTENSET    = (1 << (TIMER_INTENSET_COMPARE0_Pos + TIMER_CC_NUM - 1));
    NVIC_SetPriority(TIMER_IRQ, 2);
    NVIC_EnableIRQ(TIMER_IRQ);
}

void swarmit_uart_write(uart_t uart, const uint8_t *buffer, size_t length) {
    _devs[uart].p->EVENTS_ENDTX  = 0;
    _devs[uart].p->TXD.PTR       = (uint32_t)&length;
    _devs[uart].p->TXD.MAXCNT    = 1;
    _devs[uart].p->TASKS_STARTTX = 1;
    while (!_devs[uart].p->EVENTS_ENDTX) {
        asm volatile("" :::);
    }

    uint16_t pos = 0;
    // Send DB_UARTE_CHUNK_SIZE (64 Bytes) maximum at a time
    while (pos < length) {
        _devs[uart].p->EVENTS_ENDTX = 0;
        _devs[uart].p->TXD.PTR      = (uint32_t)&buffer[pos];
        if ((pos + DB_UARTE_CHUNK_SIZE) > length) {
            _devs[uart].p->TXD.MAXCNT = length - pos;
        } else {
            _devs[uart].p->TXD.MAXCNT = DB_UARTE_CHUNK_SIZE;
        }
        _devs[uart].p->TASKS_STARTTX = 1;
        while (!_devs[uart].p->EVENTS_ENDTX) {
            asm volatile("" :::);
        }
        pos += DB_UARTE_CHUNK_SIZE;
    }
}

//=========================== interrupts =======================================

static void _uart_isr(uart_t uart) {
    // check if the interrupt was caused by a fully received package
    if (_devs[uart].p->EVENTS_ENDRX) {
        _devs[uart].p->EVENTS_ENDRX = 0;
        // make sure we actually received new data
        if (_uart_vars[uart].state == IDLE && _uart_vars[uart].buffer[0]) {
            // first byte received, start a new frame
            _devs[uart].p->RXD.MAXCNT                    = _uart_vars[uart].buffer[0];
            _uart_vars[uart].state                       = FRAME_RX;
            NRF_UART_TIMER->TASKS_CAPTURE[TIMER_CC_NUM - 1] = 1;
            NRF_UART_TIMER->CC[TIMER_CC_NUM - 1] += 20000;
            NRF_UART_TIMER->TASKS_START = 1;
        } else if (_uart_vars[uart].state == FRAME_RX && _uart_vars[uart].callback) {
            NRF_UART_TIMER->TASKS_STOP = 1;
            // we received a frame that is smaller than half the buffer size, so we can process it now
            _devs[uart].p->RXD.PTR    = (uint32_t)_uart_vars[uart].buffer;
            _devs[uart].p->RXD.MAXCNT = 1;
            _uart_vars[uart].callback(_uart_vars[uart].buffer, _devs[uart].p->RXD.AMOUNT);
            _uart_vars[uart].state = IDLE;
        }
        _devs[uart].p->TASKS_STARTRX = 1;
    }
};

void UARTE0_UART0_IRQHandler(void) {
    _uart_isr(0);
}

void UARTE1_IRQHandler(void) {
    _uart_isr(1);
}

void TIMER4_IRQHandler(void) {
    if (NRF_UART_TIMER->EVENTS_COMPARE[TIMER_CC_NUM - 1]) {
        NRF_UART_TIMER->EVENTS_COMPARE[TIMER_CC_NUM - 1] = 0;
        NRF_UART_TIMER->TASKS_STOP                       = 1;
        _devs[0].p->RXD.MAXCNT                           = 1;
        _uart_vars[0].state                              = IDLE;
        _devs[0].p->TASKS_STARTRX                        = 1;
    }
}
