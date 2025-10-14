/**
 * @file
 * @author  Alexandre Abadie <alexandre.abadie@inria.fr>
 * @brief   Fault handlers definitions
 *
 * Adapted from @url https://wiki.segger.com/Cortex-M_Fault
 *
 * @copyright Inria, 2024
 *
 */


#ifndef __FAULT_HANDLERS_H
#define __FAULT_HANDLERS_H

#include <stdint.h>
#include <nrf.h>

#if defined(DEBUG)

static struct {
    struct {
        volatile uint32_t r0;           // Register R0
        volatile uint32_t r1;           // Register R1
        volatile uint32_t r2;           // Register R2
        volatile uint32_t r3;           // Register R3
        volatile uint32_t r12;          // Register R12
        volatile uint32_t lr;           // Link register
        volatile uint32_t pc;           // Program counter
        union {
            volatile uint32_t word;
            struct {
                uint32_t IPSR :  8;     // Interrupt Program Status register (IPSR)
                uint32_t EPSR : 19;     // Execution Program Status register (EPSR)
                uint32_t APSR :  5;     // Application Program Status register (APSR)
            } bits;
        } psr;                          // Program status register.
    } regs;

    union {
        volatile uint32_t word;
        struct {
            uint32_t MEMFAULTACT        :  1;   // [0]  Read as 1 if memory management fault is active
            uint32_t BUSFAULTACT        :  1;   // [1]  Read as 1 if bus fault exception is active
            uint32_t HARDFAULTACT       :  1;   // [2]  Read as 1 if hard fault exception is active (ARMv8-M)
            uint32_t USGFAULTACT        :  1;   // [3]  Read as 1 if usage fault exception is active
            uint32_t SECUREFAULTACT     :  1;   // [4]  Read as 1 if secure fault exception is active (ARMv8-M)
            uint32_t NMIACT             :  1;   // [5]  Read as 1 if NMI exception is active (ARMv8-M)
            uint32_t                    :  1;
            uint32_t SVCALLACT          :  1;   // [7]  Read as 1 if SVC exception is active
            uint32_t MONITORACT         :  1;   // [8]  Read as 1 if debug monitor exception is active
            uint32_t                    :  1;
            uint32_t PENDSVACT          :  1;   // [10] Read as 1 if PendSV exception is active
            uint32_t SYSTICKACT         :  1;   // [11] Read as 1 if SYSTICK exception is active
            uint32_t USGFAULTPENDED     :  1;   // [12] Usage fault pending; higher priority exception active
            uint32_t MEMFAULTPENDED     :  1;   // [13] Memory management fault pending; higher priority exception active
            uint32_t BUSFAULTPENDED     :  1;   // [14] Bus fault pending; higher priority exception active
            uint32_t SVCALLPENDED       :  1;   // [15] SVC pending; higher priority exception active
            uint32_t MEMFAULTENA        :  1;   // [16] Memory management fault exception enable
            uint32_t BUSFAULTENA        :  1;   // [17] Bus fault exception enable
            uint32_t USGFAULTENA        :  1;   // [18] Usage fault exception enable
            uint32_t SECUREFAULTENA     :  1;   // [19] Secure fault exception enable (ARMv8-M)
            uint32_t SECUREFAULTPENDED  :  1;   // [20] Secure fault exception pending; higher priority exception active (ARMv8-M)
            uint32_t HARDFAULTPENDED    :  1;   // [21] Hard fault exception pending (ARMv8-M)
            uint32_t                    : 10;
        } bits;
    } shcsr;                                   // System Handler Control and State Register (0xE000ED24)

    union {
        volatile uint8_t byte;
        struct {
            uint32_t IACCVIOL       :  1;   // [0] Instruction access violation
            uint32_t DACCVIOL       :  1;   // [1] Data access violation
            uint32_t                :  1;
            uint32_t MUNSTKERR      :  1;   // [3] Unstacking error
            uint32_t MSTKERR        :  1;   // [4] Stacking error
            uint32_t MLSPERR        :  1;   // [5] MemManage fault during FP lazy state preservation
            uint32_t                :  1;
            uint32_t MMARVALID      :  1;   // [7] Indicates the MMAR is valid
            uint32_t                : 24;
        } bits;
    } mmfsr;                                // MemManage Fault Status Register  (0xE000ED28)
    volatile uint32_t mmfar;                // MemManage Fault Address Register (0xE000ED34)

    union {
        volatile uint8_t byte;
        struct {
            uint32_t IBUSERR        :  1;   // [0] Instruction access violation
            uint32_t PRECISERR      :  1;   // [1] Precise data access violation
            uint32_t IMPRECISERR    :  1;   // [2] Imprecise data access violation
            uint32_t UNSTKERR       :  1;   // [3] Unstacking error
            uint32_t STKERR         :  1;   // [4] Stacking error
            uint32_t LSPERR         :  1;   // [5] Bus fault during FP lazy state preservation
            uint32_t                :  1;
            uint32_t BFARVALID      :  1;   // [7] Indicates BFAR is valid
            uint32_t                : 24;
        } bits;
    } bfsr;                                 // Bus Fault Status Register  (0xE000ED29)
    volatile uint32_t bfar;                 // Bus Fault Address Register (0xE000ED38)

    union {
        volatile uint16_t halfword;
        struct {
            uint32_t UNDEFINSTR     :  1;   // [0] Attempts to execute an undefined instruction
            uint32_t INVSTATE       :  1;   // [1] Attempts to switch to an invalid state (e.g., ARM)
            uint32_t INVPC          :  1;   // [2] Attempts to do an exception with a bad value in the EXC_RETURN number
            uint32_t NOCP           :  1;   // [3] Attempts to execute a coprocessor instruction
            uint32_t STKOF          :  1;   // [4] Indicates whether a stack overflow error has occurred (ARMv8-M)
            uint32_t                :  3;
            uint32_t UNALIGNED      :  1;   // [8] Indicates that an unaligned access fault has taken place
            uint32_t DIVBYZERO      :  1;   // [9] Indicates a divide by zero has taken place (can be set only if DIV_0_TRP is set)
            uint32_t                : 22;
        } bits;
    } ufsr;                                 // Usage Fault Status Register (0xE000ED2A)

    union {
        volatile uint32_t word;
        struct {
            uint32_t                :  1;
            uint32_t VECTTBL        :  1;   // [1] Indicates hard fault is caused by failed vector fetch
            uint32_t                : 28;
            uint32_t FORCED         :  1;   // [30] Indicates hard fault is taken because of bus fault/memory management fault/usage fault
            uint32_t DEBUGEVT       :  1;   // [31] Indicates hard fault is triggered by debug event
        } bits;
    } hfsr;                             // Hard Fault Status Register (0xE000ED2C)

    union {
        volatile uint32_t word;
        struct {
            uint32_t HALTED         :  1;   // [0] Halt requested in NVIC
            uint32_t BKPT           :  1;   // [1] BKPT instruction executed
            uint32_t DWTTRAP        :  1;   // [2] DWT match occurred
            uint32_t VCATCH         :  1;   // [3] Vector fetch occurred
            uint32_t EXTERNAL       :  1;   // [4] EDBGRQ signal asserted
            uint32_t PMU            :  1;   // [5] PMU counter overflow event has occurred
            uint32_t                : 26;
        } bits;
    } dfsr;                                 // Debug Fault Status Register (0xE000ED30)

    volatile uint32_t afsr;                 // Auxiliary Fault Status Register (0xE000ED3C), Vendor controlled (optional)
} hardfault_regs;

static struct {
    union {
        volatile uint32_t word;
        struct {
            uint32_t LSERR          :  1;   // [0] Lazy state error flag
            uint32_t SFARVALID      :  1;   // [1] Secure fault address valid
            uint32_t LSPERR         :  1;   // [2] Lazy state preservation error flag
            uint32_t INVTRAN        :  1;   // [3] Invalid transition flag
            uint32_t AUVIOL         :  1;   // [4] Attribution unit violation flag
            uint32_t INVER          :  1;   // [5] Invalid exception return flag
            uint32_t INVIS          :  1;   // [6] Invalid integrity signature flag
            uint32_t INVEP          :  1;   // [7] Invalid entry point
            uint32_t                : 24;
        } bits;
    } sfsr;                                 // Secure Fault Status Register
} securefault_reg;
#endif

void HardFaultHandler(uint32_t* sp);
void SecureFaultHandler(uint32_t* sp);

#endif // __FAULT_HANDLERS_H
