cmake_minimum_required(VERSION 3.20)
project(tyche_freshness_prototype LANGUAGES CXX)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "This disposable prototype currently supports Linux only")
endif()
find_package(Threads REQUIRED)
add_executable(freshness_probe main.cpp space.cpp)
target_compile_features(freshness_probe PRIVATE cxx_std_20)
target_compile_options(freshness_probe PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(freshness_probe PRIVATE Threads::Threads)
enable_testing()
add_test(NAME shared_memory_freshness_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPROBE=$<TARGET_FILE:freshness_probe>
    -DEVIDENCE_ROOT=${CMAKE_CURRENT_BINARY_DIR}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-scenarios.cmake)
set_tests_properties(shared_memory_freshness_scenarios PROPERTIES TIMEOUT 30)

add_executable(ordered_probe ordered_main.cpp space.cpp)
target_compile_features(ordered_probe PRIVATE cxx_std_20)
target_compile_options(ordered_probe PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(ordered_probe PRIVATE Threads::Threads)
add_test(NAME ordered_consumer_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPROBE=$<TARGET_FILE:ordered_probe>
    -DEVIDENCE_ROOT=${CMAKE_CURRENT_BINARY_DIR}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-scenarios.cmake)
set_tests_properties(ordered_consumer_scenarios PROPERTIES TIMEOUT 30)
