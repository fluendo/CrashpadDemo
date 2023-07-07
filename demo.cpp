#include "crashpad_helper.h"
#include <iostream>
#include <filesystem>
#include <client/crashpad_client.h>

namespace fs = std::filesystem;

int function3() {
  std::cout << "Entering function3()... BOOM!\n";
  memset(NULL, 1, 1);
  return 0;
}

int function2() {
    std::cout << "Entering function2()\n";
    return function3();
}

int function1() {
    std::cout << "Entering function1()\n";
    return function2();
}

int main() {
    std::cout << "Entering main()\n";
    fs::path db = fs::absolute(fs::path("crashpad_db"));
    fs::create_directory(db);
    fs::path crashpadHandlerPath = fs::path (CRASHPAD_HANDLER_DIR) / CRASHPAD_HANDLER_NAME;

    auto client = init("crashpaddemo", "0.1", crashpadHandlerPath.native(), db.native());
    if (client == nullptr) {
        std::cout << "Crashpad failed to unitialize.";
        return 1;
    }
    function1();
    return 0;
}