#!/bin/env python3

import gitlab
import csv
import magic
import psycopg2
import dateutil.parser
from tqdm import tqdm
from csv import reader

adminToken = 'FILL IN YOUR TOKEN'
assemblafile = 'assembladump.txt'
data = {}
lijst = []
name = None
usersNotFound = {}


def replaceURL(stringWithURL):
    while "[[url:" in stringWithURL:
        index = stringWithURL.find("[[url:")
        pipeIndex = stringWithURL[index:].find("|")
        endIndex = stringWithURL[index:].find("]]")
        if pipeIndex != -1 and pipeIndex < endIndex:
            # found a text to replace the link
            stringWithURL = stringWithURL[:index] + \
                            "[" + \
                            stringWithURL[index + pipeIndex + 1: index + endIndex] + \
                            "](" + \
                            stringWithURL[index + 6: index + pipeIndex] + \
                            ")" + \
                            stringWithURL[index + endIndex + 2:]
        else:
            # no text to replace the link
            stringWithURL = stringWithURL[:index] + \
                            stringWithURL[index + 6: index + endIndex] + \
                            stringWithURL[index + endIndex + 2:]
    return stringWithURL


# This should only be run ONCE on a new dump
#"""
# Read in the file
with open(assemblafile, 'r') as file:
    filedata = file.read()

# Replace the target string
filedata = filedata.replace('    ', '\t')
filedata = filedata.replace('\\n', '    ')
filedata = filedata.replace('\\r', '')

# Write the file out again
with open(assemblafile, 'w') as file:
    file.write(filedata)
#"""

# open the dumb and save all data in dictionary data
with open(assemblafile, encoding="utf8") as af:
    for line in reader(af, quotechar='"', delimiter=',', quoting=csv.QUOTE_ALL, skipinitialspace=True, escapechar='\\'):
        if ":fields" in line[0][-7:]:  # first line
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
                    temp[key] = values[index].replace("    ", "    \n")
                except IndexError:
                    print("ERROR")
            lijst.append(temp)
    af.close()

'''import to gitlab'''
gl = gitlab.Gitlab('https://gitlab.server.com', private_token=adminToken)

# make project
project = gl.projects.create({'name': data["spaces"][0]["name"]})
project.description = "main code base"
project.visibility = "private"
project.save()

# make map for tags: id->name
tagmap = {}
for tagname in data["tag_names"]:
    tagmap[tagname["id"]] = tagname["name"]

# make users
usermap = {'id1': 2, 'id2': 3, 'id3': 4}
usertokenmap = {}
"""
user1 = gl.users.create({'email': '', 'password': '', 'username': '', 'name': ''})
#...
"""

"""Edit database, make all users admin"""
conn = psycopg2.connect(database="gitlabhq_production", host="/var/opt/gitlab/postgresql", user="gitlab-psql",
                        port="5432", password="Fill in password")
cur = conn.cursor()
if conn:
    print("Connected to database!")

cur.execute(""" UPDATE users SET admin = (%s) WHERE admin = (%s) """, ("t", "f"))

conn.commit()
cur.close()

# add users to project
for user in gl.users.list(all=True):
    print(user)
    if user.id != 1:
        project.members.create({'user_id': user.id, 'access_level': 40.})
        i_t = user.impersonationtokens.create({'name': user.id, 'scopes': ['api']})
        usertokenmap[user.id] = i_t.token

# make milestones
milemap = {}  # assembla milestone id -> gitlab milestone id
for milestone in tqdm(data["milestones"]):
    mile = project.milestones.create({'title': milestone["title"]})
    mile.description = milestone["description"]
    if "[[url:" in mile.description:
        mile.description = replaceURL(mile.description)
    # mile.start_date = milestone["created_at"] created_at in dump komt niet overeen met waarde op assembla en ligt vaak na due date
    mile.due_date = milestone["due_date"]
    if milestone["is_completed"] == "1":
        mile.state_event = "close"
    mile.save()

    milemap[milestone["id"]] = mile.id

issuemap = {}  # assembla ticket id -> gitlab issue id
issueiidmap = {}  # assembla ticket id -> gitlab issue iid

# make map for ticket statuses: ticket status id -> ticket status name
ticketstatusmap = {}
for ticketstatus in data["ticket_statuses"]:
    ticketstatusmap[ticketstatus["id"]] = ticketstatus["name"]

# make tickets
prev = 1
for ticket in tqdm(data["tickets"]):
    # uncomment if using whole dump
    # create dummy tickets
    dummy = False
    while str(prev) != ticket["number"]:
        if dummy == False:
            token = adminToken
            # use the token to create a new gitlab connection
            user_gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=token)
            # change project to log in as certain user
            projects = user_gl.projects.list()
            project = projects[0]
        dummy = True
        print(prev)
        dummyissue = project.issues.create({'title': "dummy: %d" % prev})
        dummyissue.save()
        prev += 1
        dummyissue.delete()
    # log in as correct user
    user = None
    try:
        user = gl.users.get(usermap[ticket["reporter_id"]])
    except:
        print("User not found!")
        token = adminToken
        print(ticket["reporter_id"])
        usersNotFound[ticket["reporter_id"]] = ticket["id"]

    if user is not None:
        token = usertokenmap[user.id]

    # use the token to create a new gitlab connection
    user_gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=token)
    # change project to log in as certain user
    projects = user_gl.projects.list()
    project = projects[0]

    if ticket["created_on"] != "null":
        issue = project.issues.create({'title': ticket["summary"], 'description': ticket["description"], 'labels': [],
                                       'created_at': ticket["created_on"]})
    else:
        issue = project.issues.create({'title': ticket["summary"], 'description': ticket["description"], 'labels': []})

    issuemap[ticket["id"]] = issue.id
    issueiidmap[ticket["id"]] = issue.iid

    if issue.description == "null":
        issue.description = ""
    elif "[[url:" in issue.description:
        issue.description = replaceURL(issue.description)

    if ticket["assigned_to_id"] != "null":
        try:
            issue.assignee_ids = [usermap[ticket["assigned_to_id"]]]
        except:
            print("Assigned user was not found!")
            print(ticket["assigned_to_id"])
            usersNotFound[ticket["assigned_to_id"]] = ticket["id"]

    issue.weight = int(ticket["priority"]) * 2 - 2  # 1-5 -> 0, 2, 4, 6, 8
    if ticket["milestone_id"] != "null":
        issue.milestone_id = milemap[ticket["milestone_id"]]
    if ticket["state"] == "0":
        issue.state_event = "close"
    if ticket["due_date"] != "null":
        issue.due_date = ticket["due_date"]

    issue.labels.append(ticketstatusmap[ticket["ticket_status_id"]])
    issue.updated_at = ticket["updated_at"]
    issue.save()
    print("Echt ticket: " + str(prev))
    prev += 1

print(usersNotFound)

# back to root user
user_gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=adminToken)
projects = user_gl.projects.list()
project = projects[0]

# add associations to issues
for ticket_association in data["ticket_associations"]:
    try:
        issue1 = project.issues.get(issueiidmap[ticket_association["ticket1_id"]])
        issue2 = project.issues.get(issueiidmap[ticket_association["ticket2_id"]])
        link_data = {
            'target_project_id': issue2.project_id,
            'target_issue_iid': issue2.iid
        }
        src_issue, dest_issue = issue1.links.create(link_data)
    except:
        print("Error adding issue link")

# add tags to issue
for tag in data["ticket_tags"]:
    ticket_id = tag["ticket_id"]
    issue_iid = issueiidmap[ticket_id]
    issue = project.issues.get(issue_iid)
    issue.labels.append(tagmap[tag["tag_name_id"]])
    issue.save()

# add forum links to description of issues
for workflow_property_val in data["workflow_property_vals"]:
    if workflow_property_val["workflow_property_def_id"] == "25947":  # check if forum link
        try:
            issue = project.issues.get(issueiidmap[workflow_property_val["workflow_instance_id"]])
            issue.description = issue.description + "   \nForum link: " + workflow_property_val["value"]
            issue.save()
        except:
            print("Could not add forum link")
    elif workflow_property_val["workflow_property_def_id"] == "423503":
        try:
            issue = project.issues.get(issueiidmap[workflow_property_val["workflow_instance_id"]])
            issue.labels.append(workflow_property_val["value"])
            issue.save()
        except:
            print("Could not add component as tag")

# add comments to issues as correct user
for comment in tqdm(data["ticket_comments"]):
    # filter empty comments and comments that are commit backreferences
    if comment["comment"] != "null" and comment["comment"] != "" and "[[r:" not in comment["comment"]:
        user = None
        try:
            user = gl.users.get(usermap[comment["user_id"]])
        except:
            # print("User not found!")
            token = adminToken

        if user is not None:
            token = usertokenmap[user.id]
        # use the token to create a new gitlab connection
        user_gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=token)
        # change project to log in as certain user
        projects = user_gl.projects.list()
        project = projects[0]
        issue = project.issues.get(issueiidmap[comment["ticket_id"]])
        try:
            note = issue.notes.create(
                {'id': comment["id"], 'ticket_iid': comment["ticket_id"], 'created_at': comment["created_on"],
                 'body': comment["comment"]})
            if "[[url:" in note.body:
                note.body = replaceURL(note.body)
                note.save()
        except:
            print("Failed note")
            print(comment["id"])
            print(comment["ticket_id"])

# add files to description
mime = magic.Magic(mime=True)

# back to root user
user_gl = gitlab.Gitlab('https://gitlab.server.com/', private_token=adminToken)
projects = user_gl.projects.list()
project = projects[0]

# add files to issues, sometimes in the description, sometimes as a note
for document in data["documents"]:
    print("working")
    filename = document["id"]

    file = None
    issue = None
    extension = ""
    uploaded_file = None
    try:
        file = open("/home/name/server.gitlabconversion/all files/%s_1" % filename[1:-1], 'rb')
        print(filename)

    except:
        print("file not found")

    if file is not None:
        extension = mime.from_file("/home/username/server.gitlabconversion/all files/%s_1" % filename[1:-1])
        uploaded_file = project.upload("%s.%s" % (filename[1:-1], extension[extension.index('/') + 1:]),
                                       filedata=file.read())
        print("%s.%s" % (filename[1:-1], extension[extension.index('/') + 1:]))
        print(extension)
        print(uploaded_file)

        try:
            issue = project.issues.get(issueiidmap[document["ticket_id"]])
            print("issue found: %s" % document["ticket_id"])
        except:
            print("issue not found: %s" % document["ticket_id"])

        if issue is not None:
            description = issue.description
            # check if file is in description, else it was in a note
            if filename[1: -1] in description:
                description = description.replace(']]', '[[')
                array = description.split("[[")
                for part in array:
                    if filename[1:-1] in part:
                        index = issue.description.find(part)
                        length = len(part)
                        issue.description = issue.description[:index - 2] + "  \n{}".format(
                            uploaded_file["markdown"]) + "  \n" + issue.description[index + length + 2:]
                        break
                issue.save()
            else:
                issue_notes = issue.notes.list()
                for issue_note in issue_notes:
                    text = issue_note.body
                    if filename[1:-1] in text:
                        text = text.replace(']]', '[[')
                        array = text.split("[[")
                        for part in array:
                            if filename[1:-1] in part:
                                index = issue_note.body.find(part)
                                length = len(part)
                                issue_note.body = issue_note.body[:index - 2] + "  \n{}".format(
                                    uploaded_file["markdown"]) + "  \n" + issue_note.body[index + length + 2:]
                        issue_note.save()

print(usersNotFound)

"""Edit database"""
conn = psycopg2.connect(database="gitlabhq_production", host="/var/opt/gitlab/postgresql", user="gitlab-psql",
                        port="5432", password="fill inpassword")
cur = conn.cursor()
if conn:
    print("Connected to database!")

cur.execute(""" UPDATE users SET admin = (%s) WHERE name != (%s) """, ("f", "Administrator"))
for ticket in data["tickets"]:
    iid = issueiidmap[ticket["id"]]
    updatedate = dateutil.parser.parse(ticket["updated_at"])
    cur.execute(""" UPDATE issues SET updated_at = (%s) WHERE iid = (%s)""", (updatedate, iid))

conn.commit()
cur.close()
