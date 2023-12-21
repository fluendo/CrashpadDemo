#include <iostream>
#include <map>
#include <string>
#include <vector>
#include <client/crashpad_client.h>
#include <client/crash_report_database.h>
#include <client/settings.h>

using namespace crashpad;

CrashpadClient* init(const std::string& appName,
                     const std::string& appVersion,
                     base::FilePath::StringType handlerPath,
                     base::FilePath::StringType crashDirPath)
{
    std::cout << "Initializing crashpad handler\n";

    base::FilePath crashDir(crashDirPath);

    // Step 1: Initialize the crashpad database
    std::unique_ptr<CrashReportDatabase> database = crashpad::CrashReportDatabase::Initialize(crashDir);
    if (database == NULL)
    {
        std::cerr << "Could not initialize database\n";
        return nullptr;
    }

    // Step 2: Enable submitting crash reports to the collection server.
    Settings* settings = database->GetSettings();
    if (settings == NULL)
    {
        std::cerr << "Could not get settings\n";
        return nullptr;
    }
    settings->SetUploadsEnabled(true);

    // Step 3: Setup configuration parameters

    // URL to post error reports when enabled
    std::string url = "https://o0.ingest.sentry.io/api/0/minidump/?sentry_key=examplePublicKey";

    // Additional metadata that will be posted to the collection server for each error report.
    // This might vary depending on the provider used
    std::map<std::string, std::string> annotations;
    annotations["product"].assign(appName);
    annotations["version"].assign(appVersion);

    //  Files to upload with the crash report - default bundle size limit is 20MB
    std::vector<base::FilePath> attachments;
    /*
    base::FilePath attachment(L"./attachment.txt");
    attachments.push_back(attachment);
    */

    // Disable the rate limiting to upload all crashes
    // By default, the crashpad handler will limit uploads to one per hour.
    std::vector<std::string> arguments;
    arguments.push_back("--no-rate-limit");

    // Step 4: Start the crash handler synchronously
    CrashpadClient* client = new CrashpadClient();
    bool status = client->StartHandler(base::FilePath(handlerPath), crashDir, crashDir, url, annotations, arguments,
                                       true, false, attachments);
    if (status == false)
    {
        std::cerr << "Could not start handler\n";
        return nullptr;
    }

    return client;
}