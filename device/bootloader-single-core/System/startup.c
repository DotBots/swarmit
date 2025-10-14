/**
 * @file
 * @author Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief Startup code and vectors definition
 *
 * @copyright Inria, 2024
 *
 */

#include <stdlib.h>
#include <stdint.h>
#include <nrf.h>

#include "clock.h"

extern __NO_RETURN int main(void);

extern uint32_t __data_load_start__;
extern uint32_t __data_start__;
extern uint32_t __data_end__;
extern uint32_t __text_load_start__;
extern uint32_t __text_start__;
extern uint32_t __text_end__;
extern uint32_t __fast_load_start__;
extern uint32_t __fast_start__;
extern uint32_t __fast_end__;
extern uint32_t __ctors_load_start__;
extern uint32_t __ctors_start__;
extern uint32_t __ctors_end__;
extern uint32_t __dtors_load_start__;
extern uint32_t __dtors_start__;
extern uint32_t __dtors_end__;
extern uint32_t __rodata_load_start__;
extern uint32_t __rodata_start__;
extern uint32_t __rodata_end__;
extern uint32_t __tdata_load_start__;
extern uint32_t __tdata_start__;
extern uint32_t __tdata_end__;

extern uint32_t __bss_start__;
extern uint32_t __bss_end__;
extern uint32_t __tbss_start__;
extern uint32_t __tbss_end__;
extern uint32_t __shared_data_start__;
extern uint32_t __shared_data_end__;

extern uint32_t __heap_start__;
extern uint32_t __heap_end__;

extern uint32_t __stack_start__;
extern uint32_t __stack_end__;
extern uint32_t __stack_process_start__;
extern uint32_t __stack_process_end__;
extern uint32_t __HEAPSIZE__;
extern uint32_t __STACKSIZE__;
extern uint32_t __STACKSIZE_PROCESS__;

__NO_RETURN extern void Reset_Handler(void);
__NO_RETURN void dummy_handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void exit(int status);

// Import symbols defined by the SEGGER linker
extern void __SEGGER_RTL_init_heap(void *ptr, size_t len);

// Exceptions handlers
__attribute__ ((weak, alias("dummy_handler"))) void NMI_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void MemManage_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void BusFault_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void UsageFault_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SVC_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void DebugMon_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PendSV_Handler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SysTick_Handler(void);

void HardFault_Handler(void);

// External interrupts handlers
__attribute__ ((weak, alias("dummy_handler"))) void POWER_CLOCK_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void RADIO_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void UARTE0_UART0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SPIM1_SPIS1_TWIM1_TWIS1_SPI1_TWI1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void NFCT_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void GPIOTE_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SAADC_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TIMER0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TIMER1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TIMER2_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void RTC0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TEMP_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void RNG_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void ECB_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void CCM_AAR_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void WDT_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void RTC1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void QDEC_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void COMP_LPCOMP_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI0_EGU0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI1_EGU1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI2_EGU2_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI3_EGU3_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI4_EGU4_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SWI5_EGU5_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TIMER3_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void TIMER4_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PWM0_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PDM_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void MWU_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PWM1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PWM2_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SPIM2_SPIS2_SPI2_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void RTC2_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void I2S_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void FPU_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void USBD_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void UARTE1_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void QSPI_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void CRYPTOCELL_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void PWM3_IRQHandler(void);
__attribute__ ((weak, alias("dummy_handler"))) void SPIM3_IRQHandler(void);

// Vector table
typedef void(*vector_table_t)(void);
extern const vector_table_t _vectors[64];
const vector_table_t _vectors[64] __attribute__((used, section(".vectors"))) = {
    (vector_table_t)&__stack_end__,     //     Initial Stack Pointer
    Reset_Handler,                      //     Reset Handler
    NMI_Handler,                        // -14 NMI Handler
    HardFault_Handler,                  // -13 Hard Fault HandleR
    MemManage_Handler,                  // -12 MPU Fault Handler
    BusFault_Handler,                   // -11 Bus Fault Handler
    UsageFault_Handler,                 // -10 Usage Fault Handler
    0,                                  //     Reserved
    0,                                  //     Reserved
    0,                                  //     Reserved
    0,                                  //     Reserved
    SVC_Handler,                        //  -5 SVCall Handler
    DebugMon_Handler,                   //  -4 Debug Monitor Handler
    0,                                  //     Reserved
    PendSV_Handler,                     //  -2 PendSV Handler
    SysTick_Handler,                    //  -1 SysTick Handler

    // External Interrupts
    POWER_CLOCK_IRQHandler,
    RADIO_IRQHandler,
    UARTE0_UART0_IRQHandler,
    SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler,
    SPIM1_SPIS1_TWIM1_TWIS1_SPI1_TWI1_IRQHandler,
    NFCT_IRQHandler,
    GPIOTE_IRQHandler,
    SAADC_IRQHandler,
    TIMER0_IRQHandler,
    TIMER1_IRQHandler,
    TIMER2_IRQHandler,
    RTC0_IRQHandler,
    TEMP_IRQHandler,
    RNG_IRQHandler,
    ECB_IRQHandler,
    CCM_AAR_IRQHandler,
    WDT_IRQHandler,
    RTC1_IRQHandler,
    QDEC_IRQHandler,
    COMP_LPCOMP_IRQHandler,
    SWI0_EGU0_IRQHandler,
    SWI1_EGU1_IRQHandler,
    SWI2_EGU2_IRQHandler,
    SWI3_EGU3_IRQHandler,
    SWI4_EGU4_IRQHandler,
    SWI5_EGU5_IRQHandler,
    TIMER3_IRQHandler,
    TIMER4_IRQHandler,
    PWM0_IRQHandler,
    PDM_IRQHandler,
    0,
    0,
    MWU_IRQHandler,
    PWM1_IRQHandler,
    PWM2_IRQHandler,
    SPIM2_SPIS2_SPI2_IRQHandler,
    RTC2_IRQHandler,
    I2S_IRQHandler,
    FPU_IRQHandler,
    USBD_IRQHandler,
    UARTE1_IRQHandler,
    QSPI_IRQHandler,
    CRYPTOCELL_IRQHandler,
    0,
    0,
    PWM3_IRQHandler,
    0,
    SPIM3_IRQHandler,
};

static void _copy(uint32_t *dst, uint32_t *src, uint32_t *end) {
    while(dst < end) {
        *dst++ = *src++;
    }
}

static void _zero(uint32_t *dst, uint32_t *end) {
    while(dst < end) {
        *dst++ = 0;
    }
}

// Entry point
void Reset_Handler(void) {
    SCB->CPACR |= ((3UL << 10*2)|(3UL << 11*2));  /* set CP10 and CP11 Full Access */

    _copy(&__data_start__, &__data_load_start__, &__data_end__);

    uint32_t *src;
    uint32_t *dst;

#if defined(DEBUG)
    src = &__text_load_start__;
    dst = &__text_start__;
    while(dst < &__text_end__) {
        if (dst == src) {
            break;
        }
        *dst++ = *src++;
    }
#endif
    _copy(&__fast_start__, &__fast_load_start__, &__fast_end__);
    _copy(&__ctors_start__, &__ctors_load_start__, &__ctors_end__);
    _copy(&__dtors_start__, &__dtors_load_start__, &__dtors_end__);

#if defined(DEBUG)
    src = &__rodata_load_start__;
    dst = &__rodata_start__;
    while(dst < &__rodata_end__) {
        if (dst == src) {
            break;
        }
        *dst++ = *src++;
    }
#endif
    src = &__tdata_load_start__;
    dst = &__tdata_start__;
    while(dst < &__tdata_end__) {
        if (dst == src) {
            *dst++ = *src++;
        }
    }

    // Zeroing bss data
    _zero(&__bss_start__, &__bss_end__);
    _zero(&__tbss_start__, &__tbss_end__);

#if defined(NRF5340_XXAA) && defined(NRF_APPLICATION) && !defined(USE_SWARMIT)
    extern uint32_t __shared_data_start__;
    extern uint32_t __shared_data_end__;
    _zero(&__shared_data_start__, &__shared_data_end__);
#endif

    // Calling constructors
    typedef void (*ctor_func_t)(void);
    ctor_func_t func = (ctor_func_t)&__ctors_start__;
    while(&func < (ctor_func_t *)&__ctors_end__) {
        func++();
    }

    SystemInit();

    db_hfclk_init();
    db_lfclk_init();

    main();
}

// Exception handlers
void HardFault_Handler(void) {
    __ASM(
         "tst    LR, #4             ;"  // Check EXC_RETURN in Link register bit 2.
         "ite    EQ                 ;"
         "mrseq  R0, MSP            ;"  // Stacking was using MSP.
         "mrsne  R0, PSP            ;"  // Stacking was using PSP.
         "b      HardFaultHandler   ;"  // Stack pointer passed through R0.
    );
}

void dummy_handler(void) {
   while(1) {
       __NOP();
   }
}
