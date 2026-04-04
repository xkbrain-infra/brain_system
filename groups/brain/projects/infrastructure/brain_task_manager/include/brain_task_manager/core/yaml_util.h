#pragma once
#include <nlohmann/json.hpp>
#include <yaml-cpp/yaml.h>

using json = nlohmann::json;

// nlohmann::json → YAML::Node
inline YAML::Node JsonToYaml(const json& j) {
  if (j.is_null())    return YAML::Node(YAML::Null);
  if (j.is_boolean()) return YAML::Node(j.get<bool>());
  if (j.is_number_unsigned()) return YAML::Node(j.get<uint64_t>());
  if (j.is_number_integer())  return YAML::Node(j.get<int64_t>());
  if (j.is_number_float())    return YAML::Node(j.get<double>());
  if (j.is_string()) return YAML::Node(j.get<std::string>());

  if (j.is_array()) {
    YAML::Node node(YAML::NodeType::Sequence);
    for (auto& item : j) node.push_back(JsonToYaml(item));
    return node;
  }

  if (j.is_object()) {
    YAML::Node node(YAML::NodeType::Map);
    for (auto& [key, val] : j.items()) node[key] = JsonToYaml(val);
    return node;
  }

  return YAML::Node(YAML::Null);
}

// YAML::Node → nlohmann::json
inline json YamlToJson(const YAML::Node& node) {
  if (!node.IsDefined() || node.IsNull()) return json(nullptr);

  if (node.IsScalar()) {
    // Only coerce to number when the whole scalar is numeric.
    // Otherwise values like 2026-03-22T05:24:09Z get truncated to 2026.
    std::string s = node.Scalar();
    if (s == "true"  || s == "True"  || s == "TRUE")  return json(true);
    if (s == "false" || s == "False" || s == "FALSE") return json(false);
    if (s == "null"  || s == "Null"  || s == "NULL" || s == "~") return json(nullptr);
    try {
      size_t idx = 0;
      auto v = std::stoll(s, &idx);
      if (idx == s.size()) return json(v);
    } catch (...) {}
    try {
      size_t idx = 0;
      auto v = std::stod(s, &idx);
      if (idx == s.size()) return json(v);
    } catch (...) {}
    return json(s);
  }

  if (node.IsSequence()) {
    json arr = json::array();
    for (auto& item : node) arr.push_back(YamlToJson(item));
    return arr;
  }

  if (node.IsMap()) {
    json obj = json::object();
    for (auto& kv : node) obj[kv.first.as<std::string>()] = YamlToJson(kv.second);
    return obj;
  }

  return json(nullptr);
}
