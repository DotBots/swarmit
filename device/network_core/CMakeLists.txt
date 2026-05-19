# netcore — the swarmit network-core firmware. Runs on nRF5340 net core
# (Cortex-M33 SOFT FLOAT, no FPU). Owns the radio (via mari) and the RNG;
# exchanges messages with the secure bootloader via IPC.

set(NET_LINKER_SCRIPT ${CMAKE_SOURCE_DIR}/cmake/targets/nrf5340-net/nrf5340_netcore.ld)

# Cortex-M33 net core: no FPU, soft float, NO DSP extension.
# (gcc-arm-none-eabi defaults cortex-m33 to having DSP; explicitly opt out
# with +nodsp so core_cm33.h doesn't trip its __DSP_PRESENT guard.)
set(NET_CPU_FLAGS
    -mcpu=cortex-m33+nodsp
    -mthumb
    -mfloat-abi=soft
)

add_executable(netcore
    Source/main.c
    Source/nvmc.c
    Source/protocol.c
    System/startup.c
    System/system_init.c
    System/fault_handlers.c

    # dotbot-libs sources (listed individually — netcore has its own
    # startup at System/startup.c, so we DO NOT link dotbot_libs
    # INTERFACE here; that would pull in the app-core cpu.c and a
    # board.c that requires a BOARD_* define net core doesn't need).
    ${DOTBOT_LIBS}/bsp/nrf/rng.c
    ${DOTBOT_LIBS}/crypto/sha256.c
    ${DOTBOT_LIBS}/crypto/soft_sha256.c   # sha256_init/update/final implementations
)

target_compile_options(netcore PRIVATE ${NET_CPU_FLAGS})

target_include_directories(netcore PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Source
    ${CMAKE_CURRENT_SOURCE_DIR}/System
    # Nordic MDK + ARM CMSIS-Core come via dotbot_nordic (linked below).
    ${DOTBOT_LIBS}/bsp
    ${DOTBOT_LIBS}/bsp/conf
    ${DOTBOT_LIBS}/drv
    ${DOTBOT_LIBS}/crypto    # sha256.h is at crypto/sha256.h, not crypto/sha256/
)

target_compile_definitions(netcore PRIVATE
    NRF5340_XXAA
    NRF_NETWORK
    __NO_FPU_ENABLE
    # ARM_MATH_ARMV8MML omitted — net core has no DSP extension and
    # gcc-arm-none-eabi rejects core_cm33.h with that define under -mcpu=cortex-m33.
    USE_LH2
    FLASH_PLACEMENT=1
)

target_link_libraries(netcore PRIVATE
    dotbot_nordic   # headers-only INTERFACE: nrf.h + core_cm33.h
    mari_libs
)

target_link_options(netcore PRIVATE
    ${NET_CPU_FLAGS}
    -T${NET_LINKER_SCRIPT}
    -Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/netcore.map
)

set_target_properties(netcore PROPERTIES LINK_DEPENDS ${NET_LINKER_SCRIPT})

add_custom_command(TARGET netcore POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:netcore> ${CMAKE_CURRENT_BINARY_DIR}/netcore.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:netcore> ${CMAKE_CURRENT_BINARY_DIR}/netcore.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:netcore>
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/netcore.hex ${CMAKE_CURRENT_BINARY_DIR}/netcore.bin
    COMMENT "netcore: hex + bin"
)
