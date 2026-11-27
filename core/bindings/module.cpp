// Python bindings for the FOPDT model and pure two-layer MPC cycle.
// Keep runtime calculations shared with C++ while Python supplies explicit plain data.
#include <pybind11/pybind11.h>

#include "crosscut/fopdt.hpp"

namespace py = pybind11;

void bind_mpc(py::module_& module);

PYBIND11_MODULE(crosscut_core, m) {
  bind_mpc(m);
  m.doc() = "C++ runtime core: FOPDT model and deterministic two-layer MPC";
  // Keyword names (y0, u) deliberately match crosscut_sim.core.Fopdt, so the two are interchangeable.
  py::class_<crosscut::Fopdt>(m, "Fopdt")
      .def(py::init<double, double, double, double, double>(), py::arg("gain"), py::arg("tau_s"),
           py::arg("delay_s"), py::arg("dt_s"), py::arg("y0") = 0.0)
      .def("update", &crosscut::Fopdt::update, py::arg("u"))
      .def_property_readonly("value", &crosscut::Fopdt::value)
      .def_property_readonly("delay_samples", &crosscut::Fopdt::delay_samples);
}
