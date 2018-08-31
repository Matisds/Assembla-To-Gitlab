#!/bin/env python3
import gitlab
import csv
from tqdm import tqdm
from csv import reader

import os
import time

adminToken = 'Your_token'
assemblafile = 'dumpAssembla.txt'
data = {}
lijst = []
name = None

with open(assemblafile, encoding="utf8") as af:
    for line in reader(af, quotechar='"', delimiter=',', quoting=csv.QUOTE_ALL, skipinitialspace=True):
        if ":fields" in line[0][-7:]:  # first line #laatste field wordt niet gelezen?
            if name:
                print(name)
                data[name] = lijst
            name = line[0][:line[0].index(':')]
            data[name] = []
            keys = line
            keys.pop(0)
            keys[0] = keys[0][2:-1]
            keys[-1] = keys[-1][:-1]
            lijst = []
        else:  # following lines
            temp = {}
            values = line
            values.pop(0)
            values[0] = values[0][1:]
            values[-1] = values[-1][:-1]
            for index, key in enumerate(keys):
                try:
                    temp[key] = values[index]
                except IndexError:
                    print("ERROR")
            lijst.append(temp)
    af.close()

gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=adminToken)

# make the space (only 1)
for space in data["spaces"]:
    group = gl.groups.create({'name': space["name"], 'path': space["name"]})

# add all projects with their correct names
for space_tool in tqdm(data["space_tools"]):
    if space_tool["url"] != "null" and space_tool["type"] == "GitTool":
        projectName = space_tool["url"][
                      22 + len(data["spaces"][0]["name"]):-4]  # this will be overwritten if a better name is found
        # search for a better name in spacetool settings
        # the space_tool_id should match and the key_id should be 343 to get the name
        for space_tool_setting in data["space_tool_settings"]:
            if space_tool_setting["space_tool_id"] == space_tool["id"][1:-1] and space_tool_setting["key_id"] == "343":
                if space_tool_setting["key_id"] == "343":
                    projectName = space_tool_setting["value"].replace(" ", "_")

        print(projectName)
        project = gl.projects.create({'name': projectName, 'namespace_id': group.id})

        # initial push using a test file, will be overwritten later
        f = project.files.create({'file_path': 'testfile.txt',
                                  'branch': 'master',
                                  'content': 'test',
                                  'author_email': 'email',
                                  'author_name': 'Administrator',
                                  'commit_message': 'Create testfile'})
        # make sure the file can be overwritten, turn off protection
        time.sleep(20)  # otherwise the branch is not made yet
        p_branch = project.protectedbranches.list()[0]
        p_branch.delete()
        # wait half a minute
        time.sleep(30)
        # push repo
        os.system("git clone --mirror " + space_tool["url"])
        os.chdir(data["spaces"][0]["name"] + "." + space_tool["url"][22 + len(data["spaces"][0]["name"]):])
        os.system("git remote set-url --push origin " + "git@gitlab.server.com:" + data["spaces"][0][
            "name"] + "/" + projectName + ".git")
        os.system("git push --mirror")
        os.chdir('..')

        # git clone --mirror git@git.assembla.com:blabla.git
        # cd blabla.git
        # git remote set-url --push origin http://localhost/root/bla.git
        # git push --mirror

        print("done")
