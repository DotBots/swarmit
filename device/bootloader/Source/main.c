/**
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief Device bootloader application
 *
 * @copyright Inria, 2024
 *
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>

#include <arm_cmse.h>
#include <nrf.h>

#include "ipc.h"
#include "nvmc.h"
#include "protocol.h"
#include "tdma_client.h"
#include "tz.h"

// DotBot-firmware includes
#include "board_config.h"
#include "lh2.h"
#include "move.h"
#include "timer_hf.h"

#define SWARMIT_BASE_ADDRESS    (0x8000)
#define RADIO_FREQ              (8U)

#define LH2_UPDATE_DELAY_US        (100000UL)   ///< 100ms delay between each LH2 data refresh
#define ROBOT_REDUCE_SPEED_FACTOR  (0.7)  ///< Reduction factor applied to speed when close to target or error angle is too large
#define ROBOT_REDUCE_SPEED_ANGLE   (25)   ///< Max angle amplitude where speed reduction factor is applied
#define ROBOT_ANGULAR_SPEED_FACTOR (35)   ///< Constant applied to the normalized angle to target error
#define ROBOT_ANGULAR_SIDE_FACTOR  (-1)   ///< Angular side factor

extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

typedef struct {
    uint8_t     notification_buffer[255]  __attribute__((aligned));
    uint32_t    base_addr;
    bool        ota_start_request;
    bool        ota_chunk_request;
    bool        start_application;
    //bool        reset_application;
#if defined(USE_LH2)
    db_lh2_t    lh2;
    bool        lh2_location;
    bool        lh2_update;
#endif
} bootloader_app_data_t;

#if defined(USE_LH2)
typedef struct {
    int16_t current_angle;
    bool refresh;
} control_loop_data_t;

static control_loop_data_t _control_loop_vars = { 0 };
#endif

static bootloader_app_data_t _bootloader_vars = { 0 };

typedef void (*reset_handler_t)(void) __attribute__((cmse_nonsecure_call));

typedef struct {
    uint32_t msp;                  ///< Main stack pointer
    reset_handler_t reset_handler; ///< Reset handler
} vector_table_t;

static vector_table_t *table = (vector_table_t *)SWARMIT_BASE_ADDRESS; // Image should start with vector table

static void setup_watchdog1(void) {

    // Configuration: keep running while sleeping + pause when halted by debugger
    NRF_WDT1_S->CONFIG = (WDT_CONFIG_SLEEP_Run << WDT_CONFIG_SLEEP_Pos);

    // Enable reload register 0
    NRF_WDT1_S->RREN = WDT_RREN_RR0_Enabled << WDT_RREN_RR0_Pos;

    // Configure timeout and callback
    NRF_WDT1_S->CRV = 32768 - 1;
}

static void setup_watchdog0(void) {

    // Configuration: keep running while sleeping + pause when halted by debugger
    NRF_WDT0_S->CONFIG = (WDT_CONFIG_SLEEP_Run << WDT_CONFIG_SLEEP_Pos |
                         WDT_CONFIG_HALT_Pause << WDT_CONFIG_HALT_Pos);

    // Enable reload register 0
    NRF_WDT0_S->RREN = WDT_RREN_RR0_Enabled << WDT_RREN_RR0_Pos;

    // Configure timeout and callback
    NRF_WDT0_S->CRV = 32768 - 1;
    NRF_WDT0_S->TASKS_START = WDT_TASKS_START_TASKS_START_Trigger << WDT_TASKS_START_TASKS_START_Pos;
}

static void setup_ns_user(void) {

    // Prioritize Secure exceptions over Non-Secure
    // Set non-banked exceptions to target Non-Secure
    // Disable software reset
    uint32_t aircr = SCB->AIRCR & (~(SCB_AIRCR_VECTKEY_Msk));
    aircr |= SCB_AIRCR_PRIS_Msk | SCB_AIRCR_BFHFNMINS_Msk | SCB_AIRCR_SYSRESETREQS_Msk;
    SCB->AIRCR = ((0x05FAUL << SCB_AIRCR_VECTKEY_Pos) & SCB_AIRCR_VECTKEY_Msk) | aircr;

    // Allow FPU in non secure
    SCB->NSACR |= (1UL << SCB_NSACR_CP10_Pos) | (1UL << SCB_NSACR_CP11_Pos);

    // Enable secure fault handling
    SCB->SHCSR |= SCB_SHCSR_SECUREFAULTENA_Msk;

    // Enable div by zero usage fault
    SCB->CCR |= SCB_CCR_DIV_0_TRP_Msk;

    // Enable not aligned access fault
    SCB->CCR |= SCB_CCR_UNALIGN_TRP_Msk;

    // Disable SAU in order to use SPU instead
    SAU->CTRL = 0;;
    SAU->CTRL |= 1 << 1;  // Make all memory non secure

    // Configure secure RAM. One RAM region takes 8KiB so secure RAM is 32KiB.
    tz_configure_ram_secure(0, 3);
    // Configure non secure RAM
    tz_configure_ram_non_secure(4, 48);

    // Configure Non Secure Callable subregion
    NRF_SPU_S->FLASHNSC[0].REGION = 1;
    NRF_SPU_S->FLASHNSC[0].SIZE = 8;

    // Configure access to allows peripherals from non secure world
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_I2S0);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_I2S0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_P0_P1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_PDM0);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_PDM0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_COMP_LPCOMP);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU2);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU3);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU4);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_EGU5);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_PWM0);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_PWM0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_PWM1);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_PWM1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_PWM2);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_PWM2);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_PWM3);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_PWM3);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_QDEC0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_QDEC1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_QSPI);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_QSPI);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_RTC0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_RTC1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SAADC);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SAADC);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM0_SPIS0_TWIM0_TWIS0_UARTE0);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM0_SPIS0_TWIM0_TWIS0_UARTE0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM1_SPIS1_TWIM1_TWIS1_UARTE1);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM1_SPIS1_TWIM1_TWIS1_UARTE1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM2_SPIS2_TWIM2_TWIS2_UARTE2);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM2_SPIS2_TWIM2_TWIS2_UARTE2);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM3_SPIS3_TWIM3_TWIS3_UARTE3);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM3_SPIS3_TWIM3_TWIS3_UARTE3);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM4);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM4);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_TIMER0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_TIMER1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_TIMER2);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_USBD);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_USBD);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_USBREGULATOR);

    // Set interrupt state as non secure for non secure peripherals
    NVIC_SetTargetState(I2S0_IRQn);
    NVIC_SetTargetState(PDM0_IRQn);
    NVIC_SetTargetState(EGU0_IRQn);
    NVIC_SetTargetState(EGU1_IRQn);
    NVIC_SetTargetState(EGU2_IRQn);
    NVIC_SetTargetState(EGU3_IRQn);
    NVIC_SetTargetState(EGU4_IRQn);
    NVIC_SetTargetState(EGU5_IRQn);
    NVIC_SetTargetState(PWM0_IRQn);
    NVIC_SetTargetState(PWM1_IRQn);
    NVIC_SetTargetState(PWM2_IRQn);
    NVIC_SetTargetState(PWM3_IRQn);
    NVIC_SetTargetState(QDEC0_IRQn);
    NVIC_SetTargetState(QDEC1_IRQn);
    NVIC_SetTargetState(QSPI_IRQn);
    NVIC_SetTargetState(RTC0_IRQn);
    NVIC_SetTargetState(RTC1_IRQn);
    NVIC_SetTargetState(SAADC_IRQn);
    NVIC_SetTargetState(SPIM0_SPIS0_TWIM0_TWIS0_UARTE0_IRQn);
    NVIC_SetTargetState(SPIM1_SPIS1_TWIM1_TWIS1_UARTE1_IRQn);
    NVIC_SetTargetState(SPIM2_SPIS2_TWIM2_TWIS2_UARTE2_IRQn);
    NVIC_SetTargetState(SPIM3_SPIS3_TWIM3_TWIS3_UARTE3_IRQn);
    NVIC_SetTargetState(SPIM4_IRQn);
    NVIC_SetTargetState(TIMER0_IRQn);
    NVIC_SetTargetState(TIMER1_IRQn);
    NVIC_SetTargetState(TIMER2_IRQn);
    NVIC_SetTargetState(USBD_IRQn);
    NVIC_SetTargetState(USBREGULATOR_IRQn);
    NVIC_SetTargetState(GPIOTE0_IRQn);
    NVIC_SetTargetState(GPIOTE1_IRQn);

    // All GPIOs are non secure
    NRF_SPU_S->GPIOPORT[0].PERM = 0;
    NRF_SPU_S->GPIOPORT[1].PERM = 0;

    __DSB(); // Force memory writes before continuing
    __ISB(); // Flush and refill pipeline with updated permissions
}

uint64_t _deviceid(void) {
    return ((uint64_t)NRF_FICR_S->INFO.DEVICEID[1]) << 32 | (uint64_t)NRF_FICR_S->INFO.DEVICEID[0];
}

#if defined(USE_LH2)
static void _update_lh2(void) {
    _bootloader_vars.lh2_update = true;
}

static void _process_lh2(void) {
    if (_bootloader_vars.lh2.data_ready[0][0] == DB_LH2_PROCESSED_DATA_AVAILABLE && _bootloader_vars.lh2.data_ready[1][0] == DB_LH2_PROCESSED_DATA_AVAILABLE) {
        db_lh2_stop();
        // Prepare the radio buffer
        size_t length = protocol_header_to_buffer(_bootloader_vars.notification_buffer, BROADCAST_ADDRESS);
        _bootloader_vars.notification_buffer[length++] = PROTOCOL_DOTBOT_DATA;
        memcpy(_bootloader_vars.notification_buffer + length, &_control_loop_vars.current_angle, sizeof(int16_t));
        length += sizeof(int16_t);
        _bootloader_vars.notification_buffer[length++] = LH2_SWEEP_COUNT;
        // Add the LH2 sweep
        for (uint8_t lh2_sweep_index = 0; lh2_sweep_index < LH2_SWEEP_COUNT; lh2_sweep_index++) {
            memcpy(_bootloader_vars.notification_buffer + length, &_bootloader_vars.lh2.raw_data[lh2_sweep_index][0], sizeof(db_lh2_raw_data_t));
            length += sizeof(db_lh2_raw_data_t);

            // Mark the data as already sent
            _bootloader_vars.lh2.data_ready[lh2_sweep_index][0] = DB_LH2_NO_NEW_DATA;
        }

        // Send the radio packet
        tdma_client_tx(_bootloader_vars.notification_buffer, length);

        db_lh2_start();
    }
    _bootloader_vars.lh2_update = false;
}

static void _compute_angle(const protocol_lh2_location_t *head, const protocol_lh2_location_t *tail, int16_t *angle) {
    float dx = ((float)head->x - (float)tail->x) / 1e6;
    float dy = ((float)head->y - (float)tail->y) / 1e6;
    float distance = sqrtf(powf(dx, 2) + powf(dy, 2));

    int8_t sideFactor = (dx > 0) ? -1 : 1;
    *angle = (int16_t)(acosf(dy / distance) * 180 / M_PI) * sideFactor;
    if (*angle < 0) {
        *angle = 360 + *angle;
    }
}

static void _update_control_loop(void) {
    if (!_control_loop_vars.refresh) {
        return;
    }

    // Move straight to compute the current angle
    if (_control_loop_vars.current_angle == -1000) {
        _control_loop_vars.refresh = false;
        const protocol_lh2_location_t start_location = {
            .x = ipc_shared_data.current_location.x,
            .y = ipc_shared_data.current_location.y,
        };
        // Move straight over 10cm
        db_move_straight(10, 50);

        // Recompute angle
        _compute_angle((const protocol_lh2_location_t *)&ipc_shared_data.current_location, &start_location, &_control_loop_vars.current_angle);
        _control_loop_vars.refresh = true;
        return;
    }

    // Compute angle to target and rotate
    int16_t angle_to_target = 0;
    _compute_angle((const protocol_lh2_location_t *)&ipc_shared_data.target_location, (const protocol_lh2_location_t *)&ipc_shared_data.current_location, &angle_to_target);
    int16_t error_angle = angle_to_target - _control_loop_vars.current_angle;
    if (error_angle != 0) {
        _control_loop_vars.refresh = false;
        // Rotate
        db_move_rotate(error_angle, 45);

        _control_loop_vars.refresh = true;
        return;
    }

    // Compute distance and move straight if too far from target
    float dx = ((float)ipc_shared_data.target_location.x - (float)ipc_shared_data.current_location.x) / 1e6;
    float dy = ((float)ipc_shared_data.target_location.y - (float)ipc_shared_data.current_location.y) / 1e6;
    float distanceToTarget = sqrtf(powf(dx, 2) + powf(dy, 2));
    if ((uint32_t)(distanceToTarget * 1e6) > 20000) {
        _control_loop_vars.refresh = false;
        // Move straight
        db_move_straight(10, 50);
        _control_loop_vars.refresh = true;
        return;
    }

    ipc_shared_data.status = SWRMT_APPLICATION_READY;
}
#endif

int main(void) {

    setup_watchdog1();

    // First 2 flash regions (32kiB) is secure and contains the bootloader
    tz_configure_flash_secure(0, 2);
    // Configure non secure flash address space
    tz_configure_flash_non_secure(2, 62);

    // Management code
    // Application mutex must be non secure because it's shared with the network which is itself non secure
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_MUTEX);
    // Third region in RAM is used for IPC shared data structure
    tz_configure_ram_non_secure(3, 1);

    // Configure IPC interrupts and channels used to interact with the network core.
    NRF_IPC_S->INTENSET = (
                            1 << IPC_CHAN_RADIO_RX |
                            1 << IPC_CHAN_OTA_START |
                            1 << IPC_CHAN_OTA_CHUNK |
                            1 << IPC_CHAN_APPLICATION_START |
                            //1 << IPC_CHAN_APPLICATION_RESET |
                            1 << IPC_CHAN_LH2_LOCATION
                        );
    NRF_IPC_S->SEND_CNF[IPC_CHAN_REQ]                   = 1 << IPC_CHAN_REQ;
    NRF_IPC_S->SEND_CNF[IPC_CHAN_LOG_EVENT]             = 1 << IPC_CHAN_LOG_EVENT;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_RADIO_RX]           = 1 << IPC_CHAN_RADIO_RX;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_START]  = 1 << IPC_CHAN_APPLICATION_START;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_STOP]   = 1 << IPC_CHAN_APPLICATION_STOP;
    //NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_RESET]  = 1 << IPC_CHAN_APPLICATION_RESET;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_OTA_START]          = 1 << IPC_CHAN_OTA_START;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_OTA_CHUNK]          = 1 << IPC_CHAN_OTA_CHUNK;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_LH2_LOCATION]       = 1 << IPC_CHAN_LH2_LOCATION;
    NVIC_EnableIRQ(IPC_IRQn);
    NVIC_ClearPendingIRQ(IPC_IRQn);
    NVIC_SetPriority(IPC_IRQn, IPC_IRQ_PRIORITY);

    // PPI connection: IPC_RECEIVE -> WDT_START
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_DPPIC);
    NRF_SPU_S->DPPI[0].PERM &= ~(SPU_DPPI_PERM_CHANNEL0_Msk);
    NRF_SPU_S->DPPI[0].LOCK |= SPU_DPPI_LOCK_LOCK_Locked << SPU_DPPI_LOCK_LOCK_Pos;
    NRF_IPC_S->PUBLISH_RECEIVE[IPC_CHAN_APPLICATION_STOP] = IPC_PUBLISH_RECEIVE_EN_Enabled << IPC_PUBLISH_RECEIVE_EN_Pos;
    NRF_WDT1_S->SUBSCRIBE_START = WDT_SUBSCRIBE_START_EN_Enabled << WDT_SUBSCRIBE_START_EN_Pos;
    NRF_DPPIC_NS->CHENSET = (DPPIC_CHENSET_CH0_Enabled << DPPIC_CHENSET_CH0_Pos);
    NRF_DPPIC_S->CHENSET = (DPPIC_CHENSET_CH0_Enabled << DPPIC_CHENSET_CH0_Pos);

    // Start the network core
    release_network_core();

    tdma_client_init(RADIO_BLE_2MBit, RADIO_FREQ);

    // Check reset reason and switch to user image if reset was not triggered by any wdt timeout
    uint32_t resetreas = NRF_RESET_S->RESETREAS;
    NRF_RESET_S->RESETREAS = NRF_RESET_S->RESETREAS;
    if (!(
        (resetreas & RESET_RESETREAS_DOG0_Detected << RESET_RESETREAS_DOG0_Pos) ||
        (resetreas & RESET_RESETREAS_DOG1_Detected << RESET_RESETREAS_DOG1_Pos)
    )) {
        // Experiment is running
        ipc_shared_data.status = SWRMT_APPLICATION_RUNNING;

        // Notify application is about to start
        size_t length = protocol_header_to_buffer(_bootloader_vars.notification_buffer, BROADCAST_ADDRESS);
        _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_STARTED;
        uint64_t device_id = _deviceid();
        memcpy(_bootloader_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
        length += sizeof(uint64_t);
        tdma_client_tx(_bootloader_vars.notification_buffer, length);

        // Initialize watchdog and non secure access
        setup_ns_user();
        setup_watchdog0();
        NVIC_SetTargetState(IPC_IRQn);

        // Set the vector table address prior to jumping to image
        SCB_NS->VTOR = (uint32_t)table;
        __TZ_set_MSP_NS(table->msp);
        __TZ_set_CONTROL_NS(0);

        // Flush and refill pipeline
        __ISB();

        // Jump to non secure image
        reset_handler_t reset_handler_ns = (reset_handler_t)(cmse_nsfptr_create(table->reset_handler));
        reset_handler_ns();

        while (1) {}
    }

    if (resetreas & RESET_RESETREAS_DOG1_Detected << RESET_RESETREAS_DOG1_Pos) {
        // Notify application is stopped
        size_t length = protocol_header_to_buffer(_bootloader_vars.notification_buffer, BROADCAST_ADDRESS);
        //size_t length = 0;
        _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_STOPPED;
        uint64_t device_id = _deviceid();
        memcpy(_bootloader_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
        length += sizeof(uint64_t);
        tdma_client_tx(_bootloader_vars.notification_buffer, length);
    }

    _bootloader_vars.base_addr = SWARMIT_BASE_ADDRESS;

#if defined(USE_LH2)
    // Initialize current angle to invalid value to force a recomputation when reset is called
    _control_loop_vars.current_angle = -1000;

    // PWM, Motors and move library initialization
    db_move_init();

    // Periodic Timer and Lighthouse initialization
    db_timer_hf_init(0);
    db_timer_hf_set_periodic_us(0, 1, LH2_UPDATE_DELAY_US, &_update_lh2);
    db_lh2_init(&_bootloader_vars.lh2, &db_lh2_d, &db_lh2_e);
    db_lh2_start();
#endif

    // Experiment is ready
    ipc_shared_data.status = SWRMT_APPLICATION_READY;

    while (1) {
        __WFE();

        if (_bootloader_vars.ota_start_request) {
            _bootloader_vars.ota_start_request = false;

            // Erase non secure flash
            uint32_t pages_count = (ipc_shared_data.ota.image_size / FLASH_PAGE_SIZE) + (ipc_shared_data.ota.image_size % FLASH_PAGE_SIZE != 0);
            printf("Pages to erase: %u\n", pages_count);
            for (uint32_t page = 0; page < pages_count; page++) {
                uint32_t addr = _bootloader_vars.base_addr + page * FLASH_PAGE_SIZE;
                printf("Erasing page %u at %p\n", page + 8, (uint32_t *)addr);
                nvmc_page_erase(page + 8);
            }
            printf("Erasing done\n");

            // Notify erase is done
            size_t length = protocol_header_to_buffer(_bootloader_vars.notification_buffer, BROADCAST_ADDRESS);
            _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_OTA_START_ACK;
            uint64_t device_id = _deviceid();
            memcpy(_bootloader_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
            length += sizeof(uint64_t);
            tdma_client_tx(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.ota_chunk_request) {
            _bootloader_vars.ota_chunk_request = false;

            // Write chunk to flash
            uint32_t addr = _bootloader_vars.base_addr + ipc_shared_data.ota.chunk_index * SWRMT_OTA_CHUNK_SIZE;
            printf("Writing chunk %d/%d at address %p\n", ipc_shared_data.ota.chunk_index, ipc_shared_data.ota.chunk_count - 1, (uint32_t *)addr);
            nvmc_write((uint32_t *)addr, (void *)ipc_shared_data.ota.chunk, ipc_shared_data.ota.chunk_size);

            // Notify chunk has been written
            size_t length = protocol_header_to_buffer(_bootloader_vars.notification_buffer, BROADCAST_ADDRESS);
            _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_OTA_CHUNK_ACK;
            uint64_t device_id = _deviceid();
            memcpy(_bootloader_vars.notification_buffer + length, &device_id, sizeof(uint64_t));
            length += sizeof(uint64_t);
            memcpy(_bootloader_vars.notification_buffer + length, (void *)&ipc_shared_data.ota.chunk_index, sizeof(uint32_t));
            length += sizeof(uint32_t);
            _bootloader_vars.notification_buffer[length++] = ipc_shared_data.ota.hashes_match;
            tdma_client_tx(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.start_application) {
            NVIC_SystemReset();
        }

#if defined(USE_LH2)
        if (_bootloader_vars.lh2_update) {
            // Copy LH2 code from dotbot application
            _process_lh2();
        }

        if (_bootloader_vars.lh2_location && ipc_shared_data.status == SWRMT_APPLICATION_RESETTING) {
            _update_control_loop();
        }
#endif
    }
}

//=========================== interrupt handlers ===============================

void IPC_IRQHandler(void) {

    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_OTA_START]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_OTA_START] = 0;
        _bootloader_vars.ota_start_request = true;
    }

    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_OTA_CHUNK]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_OTA_CHUNK] = 0;
        _bootloader_vars.ota_chunk_request = true;
    }

    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_APPLICATION_START]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_APPLICATION_START] = 0;
        _bootloader_vars.start_application = true;
    }

    //if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_APPLICATION_RESET]) {
    //    NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_APPLICATION_RESET] = 0;
    //    _bootloader_vars.reset_application = true;
    //}

#if defined(USE_LH2)
    if (NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_LH2_LOCATION]) {
        NRF_IPC_S->EVENTS_RECEIVE[IPC_CHAN_LH2_LOCATION] = 0;
        _bootloader_vars.lh2_location = true;
    }
#endif
}
