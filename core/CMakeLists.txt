cmake_minimum_required(VERSION 3.20)
project(crosscut_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)  # no C++20 modules used; avoids the dependency scanner

option(CROSSCUT_BUILD_TESTS "Build the GoogleTest unit tests" ON)
option(CROSSCUT_BUILD_PYTHON "Build the pybind11 module" ON)
option(CROSSCUT_SANITIZE "Enable AddressSanitizer and UndefinedBehaviorSanitizer (GCC/Clang)" OFF)

add_library(crosscut_core_lib STATIC src/fopdt.cpp)
target_include_directories(crosscut_core_lib PUBLIC include)
set_target_properties(crosscut_core_lib PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(MSVC)
  target_compile_options(crosscut_core_lib PRIVATE /W4 /WX /permissive-)
else()
  target_compile_options(crosscut_core_lib PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

if(CROSSCUT_SANITIZE AND NOT MSVC)
  target_compile_options(crosscut_core_lib PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(crosscut_core_lib PUBLIC -fsanitize=address,undefined)
endif()

include(FetchContent)

if(CROSSCUT_BUILD_TESTS)
  enable_testing()
  FetchContent_Declare(
    googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.zip
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  add_executable(crosscut_core_tests tests/test_fopdt.cpp)
  target_link_libraries(crosscut_core_tests PRIVATE crosscut_core_lib GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(crosscut_core_tests)
endif()

if(CROSSCUT_BUILD_PYTHON)
  find_package(Python 3.11 COMPONENTS Interpreter Development.Module REQUIRED)
  FetchContent_Declare(
    pybind11
    URL https://github.com/pybind/pybind11/archive/refs/tags/v2.13.6.zip
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  FetchContent_MakeAvailable(pybind11)
  pybind11_add_module(crosscut_core bindings/module.cpp)
  target_link_libraries(crosscut_core PRIVATE crosscut_core_lib)
endif()
