/**
 * @file
 * @ingroup bsp_uart
 *
 * @brief  nRF52833-specific definition of the "uart" bsp module.
 *
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 *
 * @copyright Inria, 2022
 */

#include <stdint.h>
#include <stdlib.h>
#include <nrf.h>
#include <nrf_peripherals.h>

#include "gpio.h"
#include "uart.h"

//=========================== defines ==========================================

#define UARTE_CHUNK_SIZE (64U)

typedef struct {
    NRF_UARTE_Type *p;
    IRQn_Type       irq;
} uart_conf_t;

typedef struct {
    uint8_t      byte;      ///< the byte where received byte on UART is stored
    uart_rx_cb_t callback;  ///< pointer to the callback function
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

void db_uart_init(uart_t uart, const gpio_t *rx_pin, const gpio_t *tx_pin, uint32_t baudrate, uart_rx_cb_t callback) {

    // configure UART pins (RX as input, TX as output);
    db_gpio_init(rx_pin, GPIO_IN_PU);
    db_gpio_init(tx_pin, GPIO_OUT);

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
        _devs[uart].p->RXD.PTR       = (uint32_t)&_uart_vars[uart].byte;
        _devs[uart].p->INTENSET      = (UARTE_INTENSET_ENDRX_Enabled << UARTE_INTENSET_ENDRX_Pos);
        _devs[uart].p->SHORTS        = (UARTE_SHORTS_ENDRX_STARTRX_Enabled << UARTE_SHORTS_ENDRX_STARTRX_Pos);
        _devs[uart].p->TASKS_STARTRX = 1;
        NVIC_EnableIRQ(_devs[uart].irq);
        NVIC_SetPriority(_devs[uart].irq, 0);
        NVIC_ClearPendingIRQ(_devs[uart].irq);
    }
}

void db_uart_write(uart_t uart, uint8_t *buffer, size_t length) {
    uint8_t pos = 0;
    // Send UARTE_CHUNK_SIZE (64 Bytes) maximum at a time
    while ((pos % UARTE_CHUNK_SIZE) == 0 && pos < length) {
        _devs[uart].p->EVENTS_ENDTX = 0;
        _devs[uart].p->TXD.PTR      = (uint32_t)&buffer[pos];
        if ((pos + UARTE_CHUNK_SIZE) > length) {
            _devs[uart].p->TXD.MAXCNT = length - pos;
        } else {
            _devs[uart].p->TXD.MAXCNT = UARTE_CHUNK_SIZE;
        }
        _devs[uart].p->TASKS_STARTTX = 1;
        while (_devs[uart].p->EVENTS_ENDTX == 0) {}
        pos += UARTE_CHUNK_SIZE;
    }
}

//=========================== interrupts =======================================

static void _uart_isr(uart_t uart) {
    // check if the interrupt was caused by a fully received package
    if (_devs[uart].p->EVENTS_ENDRX) {
        _devs[uart].p->EVENTS_ENDRX = 0;
        // make sure we actually received new data
        if (_devs[uart].p->RXD.AMOUNT != 0) {
            // process received byte
            _uart_vars[uart].callback(_uart_vars[uart].byte);
        }
    }
};

void UARTE0_UART0_IRQHandler(void) {
    _uart_isr(0);
}

void UARTE1_IRQHandler(void) {
    _uart_isr(1);
}
