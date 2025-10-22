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

#include "battery.h"
#include "ipc.h"
#include "nvmc.h"
#include "protocol.h"
#include "mari.h"
#include "tz.h"

// DotBot-firmware includes
#include "board_config.h"
#include "gpio.h"
#include "localization.h"
#include "motors.h"
#include "move.h"
#include "timer.h"

#define SWARMIT_BASE_ADDRESS        (0x10000)

#define BATTERY_UPDATE_DELAY        (1000U)
#define POSITION_UPDATE_DELAY_MS    (500U) ///< 100ms delay between each position update

#define ROBOT_DISTANCE_THRESHOLD    (0.05)
#define ROBOT_DIRECTION_THRESHOLD   (0.01)
#define ROBOT_ROTATE_SPEED          (45)
#define ROBOT_STRAIGHT_SPEED        (45)
#define ROBOT_MAX_SPEED             (50)   ///< Max speed in autonomous control mode
#define ROBOT_REDUCE_SPEED_FACTOR   (0.8)  ///< Reduction factor applied to speed when close to target or error angle is too large
#define ROBOT_REDUCE_SPEED_ANGLE    (25)   ///< Max angle amplitude where speed reduction factor is applied
#define ROBOT_ANGULAR_SPEED_FACTOR  (35)   ///< Constant applied to the normalized angle to target error
#define ROBOT_ANGULAR_SIDE_FACTOR   (-1)   ///< Angular side factor

extern volatile __attribute__((section(".shared_data"))) ipc_shared_data_t ipc_shared_data;

typedef struct {
    uint8_t         notification_buffer[255]  __attribute__((aligned));
    uint32_t        base_addr;
    bool            ota_start_request;
    bool            ota_require_erase;
    bool            ota_chunk_request;
    bool            start_application;
    position_2d_t   last_position;
    bool            position_update;
    bool            battery_update;
} bootloader_app_data_t;

typedef struct {
    position_2d_t   previous_position;
    int16_t         direction;
    bool            initial_direction_compensated;
    bool            final_direction_compensated;
    bool            target_reached;
} control_loop_data_t;

static control_loop_data_t _control_loop_vars = { 0 };
static const gpio_t _status_led = { .port = 1, .pin = 5 };  // TODO: use board specific values

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
    NRF_SPU_S->FLASHNSC[0].REGION = 3;
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
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM0_SPIS0_TWIM0_TWIS0_UARTE0);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM0_SPIS0_TWIM0_TWIS0_UARTE0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM1_SPIS1_TWIM1_TWIS1_UARTE1);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM1_SPIS1_TWIM1_TWIS1_UARTE1);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM2_SPIS2_TWIM2_TWIS2_UARTE2);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM2_SPIS2_TWIM2_TWIS2_UARTE2);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM3_SPIS3_TWIM3_TWIS3_UARTE3);
    tz_configure_periph_dma_non_secure(NRF_APPLICATION_PERIPH_ID_SPIM3_SPIS3_TWIM3_TWIS3_UARTE3);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_TIMER0);
    tz_configure_periph_non_secure(NRF_APPLICATION_PERIPH_ID_TIMER1);
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
    NVIC_SetTargetState(SPIM0_SPIS0_TWIM0_TWIS0_UARTE0_IRQn);
    NVIC_SetTargetState(SPIM1_SPIS1_TWIM1_TWIS1_UARTE1_IRQn);
    NVIC_SetTargetState(SPIM2_SPIS2_TWIM2_TWIS2_UARTE2_IRQn);
    NVIC_SetTargetState(SPIM3_SPIS3_TWIM3_TWIS3_UARTE3_IRQn);
    NVIC_SetTargetState(TIMER0_IRQn);
    NVIC_SetTargetState(TIMER1_IRQn);
    NVIC_SetTargetState(USBD_IRQn);
    NVIC_SetTargetState(USBREGULATOR_IRQn);
    NVIC_SetTargetState(GPIOTE0_IRQn);
    NVIC_SetTargetState(GPIOTE1_IRQn);

    // Configure non-secure GPIOs
    NRF_SPU_S->GPIOPORT[0].PERM = 0;
    NRF_SPU_S->GPIOPORT[1].PERM = 0;

    // Set LH2 pins as secure
    NRF_SPU_S->GPIOPORT[DB_LH2_E_PORT].PERM |= (1 << DB_LH2_E_PIN);
    NRF_SPU_S->GPIOPORT[DB_LH2_D_PORT].PERM |= (1 << DB_LH2_D_PIN);
    NRF_SPU_S->GPIOPORT[1].PERM |= (1 << 4);
#if defined(BOARD_DOTBOT_V3)
    NRF_SPU_S->GPIOPORT[1].PERM |= (1 << 7);
#else
    NRF_SPU_S->GPIOPORT[1].PERM |= (1 << 6);
#endif

    // Set AIN1 as secure, only for reading battery level on dotvot-v3
#if defined(BOARD_DOTBOT_V3)
    NRF_SPU_S->GPIOPORT[0].PERM |= (1 << 5); // AIN1 is P0.5
#endif

    __DSB(); // Force memory writes before continuing
    __ISB(); // Flush and refill pipeline with updated permissions
}

static void _update_position(void) {
    _bootloader_vars.position_update = true;
}

static void _read_battery(void) {
    _bootloader_vars.battery_update = true;
}

static void _compute_angle(const position_2d_t *head, const position_2d_t *tail, int16_t *angle) {
    float dx = ((float)head->x / 1e6) - ((float)tail->x / 1e6);
    float dy = ((float)head->y / 1e6) - ((float)tail->y / 1e6);
    float distance = sqrtf(powf(dx, 2) + powf(dy, 2));

    if (distance < ROBOT_DIRECTION_THRESHOLD) {
        return;
    }

    int8_t sideFactor = (dx > 0) ? -1 : 1;
    int16_t result = (int16_t)(acosf(dy / distance) * 180 / M_PI) * sideFactor;
    if (result < -360) {
        result += 360;
    }
    *angle = result;
}

static void _compensate_angle(int16_t angle) {
    int8_t speed = ROBOT_ROTATE_SPEED * -1;

    if (angle < 0) {
        speed *= -1;
        angle *= -1;
    }
    db_move_rotate(angle, speed);
}

static void _compensate_initial_direction(void) {
    // Move straight to be able to compute the current angle
    if (_control_loop_vars.direction == -1000) {
        db_move_straight(50, 50);
        return;
    }

    // Compute angle to target and rotate
    int16_t angle_to_target = 0;
    _compute_angle((const position_2d_t *)&ipc_shared_data.target_position, (const position_2d_t *)&_bootloader_vars.last_position, &angle_to_target);
    int16_t error_angle = angle_to_target - _control_loop_vars.direction;
    _compensate_angle(error_angle);
    db_move_straight(ROBOT_STRAIGHT_SPEED, ROBOT_STRAIGHT_SPEED);
    _control_loop_vars.initial_direction_compensated = true;
}

static void _update_control_loop(void) {
    if (ipc_shared_data.status != SWRMT_APPLICATION_RESETTING) {
        return;
    }

    float dx = ((float)ipc_shared_data.target_position.x / 1e6) - ((float)_bootloader_vars.last_position.x / 1e6);
    float dy = ((float)ipc_shared_data.target_position.y / 1e6) - ((float)_bootloader_vars.last_position.y / 1e6);
    float distanceToTarget = sqrtf(powf(dx, 2) + powf(dy, 2));
    float speedReductionFactor = 1.0;  // No reduction by default

    if ((uint32_t)(distanceToTarget) < 0.2) {
        speedReductionFactor = ROBOT_REDUCE_SPEED_FACTOR;
    }

    int16_t left_speed      = 0;
    int16_t right_speed     = 0;
    int16_t angular_speed   = 0;
    int16_t error_angle     = 0;
    int16_t angle_to_target = 0;
    if (distanceToTarget < ROBOT_DISTANCE_THRESHOLD) {
        _control_loop_vars.target_reached = true;
     } else if (_control_loop_vars.direction == -1000) {
        // Unknown direction, just move forward a bit
        left_speed  = (int16_t)ROBOT_MAX_SPEED * speedReductionFactor;
        right_speed = (int16_t)ROBOT_MAX_SPEED * speedReductionFactor;
    } else {
        // compute angle to target waypoint
        _compute_angle((const position_2d_t *)&ipc_shared_data.target_position, (const position_2d_t *)&_bootloader_vars.last_position, &angle_to_target);
        error_angle = angle_to_target - _control_loop_vars.direction;
        if (error_angle < -180) {
            error_angle += 360;
        } else if (error_angle > 180) {
            error_angle -= 360;
        }
        if (error_angle > ROBOT_REDUCE_SPEED_ANGLE || error_angle < -ROBOT_REDUCE_SPEED_ANGLE) {
            speedReductionFactor = ROBOT_REDUCE_SPEED_FACTOR;
        }
        angular_speed = (int16_t)(((float)error_angle / 180) * ROBOT_ANGULAR_SPEED_FACTOR);
        left_speed    = (int16_t)(((ROBOT_MAX_SPEED * speedReductionFactor) - (angular_speed * ROBOT_ANGULAR_SIDE_FACTOR)));
        right_speed   = (int16_t)(((ROBOT_MAX_SPEED * speedReductionFactor) + (angular_speed * ROBOT_ANGULAR_SIDE_FACTOR)));
        if (left_speed > ROBOT_MAX_SPEED) {
            left_speed = ROBOT_MAX_SPEED;
        }
        if (right_speed > ROBOT_MAX_SPEED) {
            right_speed = ROBOT_MAX_SPEED;
        }
    }

    db_motors_set_speed(left_speed, right_speed);
}

int main(void) {

    setup_watchdog1();

    // First 4 flash regions (64kiB) is secure and contains the bootloader
    tz_configure_flash_secure(0, 4);
    // Configure non secure flash address space
    tz_configure_flash_non_secure(4, 60);

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
                            1 << IPC_CHAN_APPLICATION_START
                            //1 << IPC_CHAN_APPLICATION_RESET
                        );
    NRF_IPC_S->SEND_CNF[IPC_CHAN_REQ]                   = 1 << IPC_CHAN_REQ;
    NRF_IPC_S->SEND_CNF[IPC_CHAN_LOG_EVENT]             = 1 << IPC_CHAN_LOG_EVENT;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_RADIO_RX]           = 1 << IPC_CHAN_RADIO_RX;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_START]  = 1 << IPC_CHAN_APPLICATION_START;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_STOP]   = 1 << IPC_CHAN_APPLICATION_STOP;
    //NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_APPLICATION_RESET]  = 1 << IPC_CHAN_APPLICATION_RESET;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_OTA_START]          = 1 << IPC_CHAN_OTA_START;
    NRF_IPC_S->RECEIVE_CNF[IPC_CHAN_OTA_CHUNK]          = 1 << IPC_CHAN_OTA_CHUNK;
    NVIC_EnableIRQ(IPC_IRQn);
    NVIC_ClearPendingIRQ(IPC_IRQn);
    NVIC_SetPriority(IPC_IRQn, IPC_IRQ_PRIORITY);

    // PPI connection: IPC_RECEIVE -> WDT_START
    NRF_IPC_S->PUBLISH_RECEIVE[IPC_CHAN_APPLICATION_STOP] = IPC_PUBLISH_RECEIVE_EN_Enabled << IPC_PUBLISH_RECEIVE_EN_Pos;
    NRF_WDT1_S->SUBSCRIBE_START = WDT_SUBSCRIBE_START_EN_Enabled << WDT_SUBSCRIBE_START_EN_Pos;
    NRF_DPPIC_S->CHENSET = (DPPIC_CHENSET_CH0_Enabled << DPPIC_CHENSET_CH0_Pos);

    // Write device type value to shared memory
#if defined(BOARD_DOTBOT_V3)
    ipc_shared_data.device_type = SWRMT_DEVICE_TYPE_DOTBOTV3;
#elif defined(BOARD_DOTBOT_V2)
    ipc_shared_data.device_type = SWRMT_DEVICE_TYPE_DOTBOTV2;
#elif defined(BOARD_NRF5340DK)
    ipc_shared_data.device_type = SWRMT_DEVICE_TYPE_NRF5340DK;
#else
    ipc_shared_data.device_type = SWRMT_DEVICE_TYPE_UNKNOWN;
#endif

    // Start the network core
    release_network_core();

    mari_init();

    battery_level_init();
    ipc_shared_data.battery_level = battery_level_read();

    localization_init();

    // Check reset reason and switch to user image if reset was not triggered by any wdt timeout
    uint32_t resetreas = NRF_RESET_S->RESETREAS;
    NRF_RESET_S->RESETREAS = NRF_RESET_S->RESETREAS;

     //Boot user image after soft system reset
    if (resetreas & RESET_RESETREAS_SREQ_Detected << RESET_RESETREAS_SREQ_Pos) {
        // Experiment is running
        ipc_shared_data.status = SWRMT_APPLICATION_RUNNING;

        // Initialize watchdog and non secure access
        setup_ns_user();
        setup_watchdog0();
        NVIC_SetTargetState(IPC_IRQn);    // Used for radio RX
        NVIC_SetTargetState(SPIM4_IRQn);  // Used for LH2 localization

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

    _bootloader_vars.base_addr = SWARMIT_BASE_ADDRESS;
    _bootloader_vars.ota_require_erase = true;

    // Initialize current angle to invalid value to force a recomputation when reset is called
    _control_loop_vars.direction = -1000;
    _control_loop_vars.target_reached = false;
    _control_loop_vars.initial_direction_compensated = false;
    _control_loop_vars.final_direction_compensated = false;

    // PWM, Motors and move library initialization
    // Allows enable the regulator and relay switch (v3 only) pins
    db_move_init();

    // Status LED
    db_gpio_init(&_status_led, DB_GPIO_OUT);
    // Periodic Timer and Lighthouse initialization
    db_timer_init(1);
    db_timer_set_periodic_ms(1, 1, POSITION_UPDATE_DELAY_MS, &_update_position);
    db_timer_set_periodic_ms(1, 2, BATTERY_UPDATE_DELAY, &_read_battery);

    // Experiment is ready
    ipc_shared_data.status = SWRMT_APPLICATION_READY;

    while (1) {
        __WFE();

        if (_bootloader_vars.ota_start_request) {
            _bootloader_vars.ota_start_request = false;

            if (_bootloader_vars.ota_require_erase) {
                // Erase non secure flash
                uint32_t pages_count = (ipc_shared_data.ota.image_size / FLASH_PAGE_SIZE) + (ipc_shared_data.ota.image_size % FLASH_PAGE_SIZE != 0);
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
            _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_OTA_START_ACK;
            mari_node_tx(_bootloader_vars.notification_buffer, length);
        }

        if (_bootloader_vars.ota_chunk_request) {
            _bootloader_vars.ota_chunk_request = false;

            if (ipc_shared_data.ota.last_chunk_acked != (int32_t)ipc_shared_data.ota.chunk_index) {
                // Write chunk to flash
                uint32_t addr = _bootloader_vars.base_addr + ipc_shared_data.ota.chunk_index * SWRMT_OTA_CHUNK_SIZE;
                printf("Writing chunk %d/%d at address %p\n", ipc_shared_data.ota.chunk_index, ipc_shared_data.ota.chunk_count - 1, (uint32_t *)addr);
                nvmc_write((uint32_t *)addr, (void *)ipc_shared_data.ota.chunk, ipc_shared_data.ota.chunk_size);
                _bootloader_vars.ota_require_erase = true;
            }

            // Notify chunk has been written
            size_t length = 0;
            _bootloader_vars.notification_buffer[length++] = SWRMT_NOTIFICATION_OTA_CHUNK_ACK;
            memcpy(_bootloader_vars.notification_buffer + length, (void *)&ipc_shared_data.ota.chunk_index, sizeof(uint32_t));
            length += sizeof(uint32_t);
            ipc_shared_data.ota.last_chunk_acked = ipc_shared_data.ota.chunk_index;
            mari_node_tx(_bootloader_vars.notification_buffer, length);

            // If last chunk, finalize computed hash, set back to ready state
            if (ipc_shared_data.ota.chunk_index == ipc_shared_data.ota.chunk_count - 1) {
                ipc_shared_data.status = SWRMT_APPLICATION_READY;
            }
        }

        if (_bootloader_vars.start_application) {
            NVIC_SystemReset();
        }

        if (_bootloader_vars.battery_update) {
            db_gpio_toggle(&_status_led);
            mutex_lock();
            ipc_shared_data.battery_level = battery_level_read();
            mutex_unlock();
            _bootloader_vars.battery_update = false;
        }

        // Process available lighthouse data
        localization_process_data();
        if (_bootloader_vars.position_update) {
            position_2d_t position = { 0 };
            bool valid_position = localization_get_position(&position);
            if (valid_position) {
                mutex_lock();
                ipc_shared_data.current_position.x = position.x;
                ipc_shared_data.current_position.y = position.y;
                mutex_unlock();
                printf("Position (%u,%u)\n", position.x, position.y);
            } else {
                puts("Invalid position");
            }

            if (ipc_shared_data.status != SWRMT_APPLICATION_RESETTING) {
                continue;
            }

            int16_t new_direction = -1000;
            mutex_lock();
            _compute_angle(
                (const position_2d_t *)&ipc_shared_data.current_position,
                &_control_loop_vars.previous_position,
                &new_direction
            );
            mutex_unlock();
            if (new_direction != -1000) {
                _control_loop_vars.direction = new_direction;
            }
            mutex_lock();
            _control_loop_vars.previous_position.x = ipc_shared_data.current_position.x;
            _control_loop_vars.previous_position.y = ipc_shared_data.current_position.y;
            mutex_unlock();

            if (!_control_loop_vars.initial_direction_compensated) {
                _compensate_initial_direction();
            }

            if (!_control_loop_vars.target_reached) {
                _update_control_loop();
            }

            if (_control_loop_vars.target_reached) {
                _compensate_angle(_control_loop_vars.direction);
                ipc_shared_data.status = SWRMT_APPLICATION_READY;
                _control_loop_vars.direction = -1000;
                _control_loop_vars.target_reached = false;
                _control_loop_vars.initial_direction_compensated = false;
                _control_loop_vars.final_direction_compensated = false;
                _control_loop_vars.previous_position.x = 0;
                _control_loop_vars.previous_position.y = 0;
            }

            _bootloader_vars.position_update = false;
        }
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
}
